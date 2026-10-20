# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Job card states that mean the job is finished.
CLOSED_JOB_STATES = ('completed', 'cancel')


class FleetInspection(models.Model):
    _name = 'fleet.inspection'
    _description = 'Fleet Vehicle Inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    # Anyone who can read the inspection (e.g. the mechanic of a job card) may comment on it.
    _mail_post_access = 'read'

    name = fields.Char(string='Inspection No.', required=True, copy=False,
                        readonly=True, default=lambda self: _('New'))

    # --- General information -------------------------------------------------
    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', required=True,
                                  tracking=True, index=True)
    registration_number = fields.Char(related='vehicle_id.license_plate', store=True, readonly=True)
    chassis_number = fields.Char(related='vehicle_id.vin_sn', store=True, readonly=True)
    odometer = fields.Float(related='vehicle_id.odometer', string='Current Vehicle Odometer', readonly=True)
    odometer_unit = fields.Selection(related='vehicle_id.odometer_unit', readonly=True)
    odometer_reading = fields.Float(
        string='Odometer (Mileage)', tracking=True,
        help='Mileage read on the vehicle during this inspection. It is logged on the '
             'vehicle odometer history when the inspection is completed.')

    driver_id = fields.Many2one('res.partner', string='Driver', tracking=True)
    mechanic_id = fields.Many2one('hr.employee', string='Mechanic')
    supervisor_id = fields.Many2one('hr.employee', string='Supervisor')

    date = fields.Date(string='Inspection Date', default=fields.Date.context_today, required=True)
    inspection_type = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('pretrip', 'Pre-trip'),
        ('posttrip', 'Post-trip'),
        ('custom', 'Custom'),
    ], string='Inspection Type', default='pretrip', required=True)
    check_round = fields.Selection([
        ('1', 'First Check'),
        ('2', 'Second Check'),
        ('3', 'Third Check'),
        ('4', 'Fourth Check'),
    ], string='Check Round', default='1',
        help='Matches the First/Second/Third/Fourth Check columns on the paper form.')

    branch = fields.Char(string='Branch')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('approved', 'Approved'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    start_datetime = fields.Datetime(string='Started On', copy=False, readonly=True)
    end_datetime = fields.Datetime(string='Completed On', copy=False, readonly=True)
    duration = fields.Float(string='Duration (hrs)', compute='_compute_duration', store=True,
                            aggregator='avg', help='Time between starting and completing the inspection.')
    approved_by_id = fields.Many2one('res.users', string='Approved By', copy=False, readonly=True)
    approved_on = fields.Datetime(string='Approved On', copy=False, readonly=True)

    # --- Checklist -------------------------------------------------------------
    line_ids = fields.One2many('fleet.inspection.line', 'inspection_id', string='Checklist')
    defective_line_ids = fields.One2many(
        'fleet.inspection.line', 'inspection_id', string='Defects',
        domain=[('result', '=', 'defective')], readonly=True)

    total_items = fields.Integer(compute='_compute_stats', store=True)
    good_count = fields.Integer(compute='_compute_stats', store=True)
    defective_count = fields.Integer(compute='_compute_stats', store=True)
    na_count = fields.Integer(compute='_compute_stats', store=True)
    high_defect_count = fields.Integer(compute='_compute_stats', store=True)
    repeat_defect_count = fields.Integer(compute='_compute_stats', store=True)
    health_score = fields.Float(
        string='Health Score (%)', compute='_compute_stats', store=True, aggregator='avg',
        help='Share of applicable items found in good condition.')

    result = fields.Selection([
        ('pass', 'Pass'),
        ('pass_defects', 'Pass with Defects'),
        ('fail', 'Fail'),
    ], compute='_compute_stats', store=True, tracking=True)

    # --- Sign off ----------------------------------------------------------
    remarks = fields.Text(string='General Remarks')
    driver_signature = fields.Binary(string='Driver Signature')
    driver_signature_date = fields.Datetime(string='Driver Signed On')
    mechanic_signature = fields.Binary(string='Mechanic Signature')
    mechanic_signature_date = fields.Datetime(string='Mechanic Signed On')
    supervisor_signature = fields.Binary(string='Supervisor Signature')
    supervisor_signature_date = fields.Datetime(string='Supervisor Signed On')

    # --- Maintenance / job card integration ---------------------------------
    service_ids = fields.One2many('fleet.vehicle.log.services', 'inspection_id', string='Job Cards')
    service_count = fields.Integer(compute='_compute_service_count')
    unassigned_defect_count = fields.Integer(
        string='Defects without Job Card', compute='_compute_job_card_status', store=True)
    job_card_status = fields.Selection([
        ('no_defects', 'No Defects'),
        ('pending', 'Awaiting Job Card'),
        ('partial', 'Partially Assigned'),
        ('assigned', 'Job Cards Created'),
        ('repaired', 'All Defects Repaired'),
    ], string='Job Card Status', compute='_compute_job_card_status', store=True)
    fixed_defect_count = fields.Integer(
        string='Repaired Defects', compute='_compute_job_card_status', store=True)

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name, company_id)', 'The Inspection Number must be unique per company!'),
    ]

    @api.depends('service_ids')
    def _compute_service_count(self):
        for rec in self:
            rec.service_count = len(rec.service_ids)

    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime:
                rec.duration = (rec.end_datetime - rec.start_datetime).total_seconds() / 3600.0
            else:
                rec.duration = 0.0

    @api.depends('line_ids.result', 'line_ids.severity', 'line_ids.is_repeat_defect')
    def _compute_stats(self):
        for rec in self:
            lines = rec.line_ids
            rec.total_items = len(lines)
            rec.good_count = len(lines.filtered(lambda l: l.result == 'good'))
            rec.defective_count = len(lines.filtered(lambda l: l.result == 'defective'))
            rec.na_count = len(lines.filtered(lambda l: l.result == 'na'))
            rec.high_defect_count = len(lines.filtered(
                lambda l: l.result == 'defective' and l.severity == 'high'))
            rec.repeat_defect_count = len(lines.filtered(
                lambda l: l.result == 'defective' and l.is_repeat_defect))
            applicable = rec.good_count + rec.defective_count
            rec.health_score = (100.0 * rec.good_count / applicable) if applicable else 0.0
            if not lines:
                rec.result = False
            elif rec.high_defect_count:
                rec.result = 'fail'
            elif rec.defective_count:
                rec.result = 'pass_defects'
            else:
                rec.result = 'pass'

    @api.depends('line_ids.result', 'line_ids.job_card_id', 'line_ids.repair_state')
    def _compute_job_card_status(self):
        for rec in self:
            defects = rec.line_ids.filtered(lambda l: l.result == 'defective')
            unassigned = defects.filtered(lambda l: not l.job_card_id)
            rec.unassigned_defect_count = len(unassigned)
            rec.fixed_defect_count = len(defects.filtered(lambda l: l.repair_state == 'fixed'))
            if not defects:
                rec.job_card_status = 'no_defects'
            elif len(unassigned) == len(defects):
                rec.job_card_status = 'pending'
            elif unassigned:
                rec.job_card_status = 'partial'
            elif rec.fixed_defect_count == len(defects):
                rec.job_card_status = 'repaired'
            else:
                rec.job_card_status = 'assigned'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('fleet.inspection') or _('New')
            if vals.get('vehicle_id') and not vals.get('odometer_reading'):
                vals['odometer_reading'] = self.env['fleet.vehicle'].browse(vals['vehicle_id']).odometer
        return super().create(vals_list)

    # --- Checklist loading ---------------------------------------------------
    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id and self.vehicle_id.driver_id:
            self.driver_id = self.vehicle_id.driver_id
        if self.vehicle_id:
            self.odometer_reading = self.vehicle_id.odometer
        if self.vehicle_id and not self.line_ids:
            self._load_checklist()

    def _get_vehicle_category(self):
        self.ensure_one()
        return self.vehicle_id.model_id.category_id if self.vehicle_id and self.vehicle_id.model_id else False

    def _load_checklist(self):
        """(Re)build the checklist lines from configured categories/items,
        filtered by the vehicle's model category when applicable."""
        self.ensure_one()
        veh_category = self._get_vehicle_category()
        categories = self.env['fleet.inspection.category'].search([])
        commands = []
        sequence = 10
        for category in categories:
            if category.vehicle_type_ids and veh_category not in category.vehicle_type_ids:
                continue
            items = category.item_ids.filtered(
                lambda i: not i.vehicle_type_ids or veh_category in i.vehicle_type_ids)
            for item in items:
                commands.append((0, 0, {
                    'category_id': category.id,
                    'item_id': item.id,
                    'result': 'good',
                    'severity': item.default_severity,
                    'job_type_id': category.job_type_id.id,
                    'sequence': sequence,
                }))
                sequence += 10
        self.line_ids = [(5, 0, 0)] + commands

    def action_load_checklist(self):
        for rec in self:
            rec._load_checklist()
        return True

    def _flag_repeat_defects(self):
        """Mark defective lines whose item was also defective on the previous
        completed/approved inspection of the same vehicle."""
        # sudo: the previous inspection may have been made by another inspector,
        # which an inspector is not allowed to read.
        Line = self.env['fleet.inspection.line'].sudo()
        for rec in self:
            defects = rec.line_ids.filtered(lambda l: l.result == 'defective')
            rec.line_ids.filtered('is_repeat_defect').write({'is_repeat_defect': False})
            if not defects:
                continue
            previous = self.sudo().search([
                ('vehicle_id', '=', rec.vehicle_id.id),
                ('state', 'in', ('completed', 'approved')),
                ('id', '!=', rec.id),
                '|', ('date', '<', rec.date), '&', ('date', '=', rec.date), ('id', '<', rec.id),
            ], order='date desc, id desc', limit=1)
            if not previous:
                continue
            previous_items = Line.search([
                ('inspection_id', '=', previous.id), ('result', '=', 'defective'),
            ]).item_id
            defects.filtered(lambda l: l.item_id in previous_items).write({'is_repeat_defect': True})

    def _log_odometer(self):
        """Record the inspection mileage on the vehicle odometer history."""
        Odometer = self.env['fleet.vehicle.odometer'].sudo()
        for rec in self:
            if rec.odometer_reading and rec.odometer_reading > rec.vehicle_id.odometer:
                Odometer.create({
                    'vehicle_id': rec.vehicle_id.id,
                    'value': rec.odometer_reading,
                    'date': rec.date,
                })

    # --- Workflow --------------------------------------------------------------
    def action_start(self):
        for rec in self:
            if not rec.line_ids:
                rec._load_checklist()
            rec.state = 'in_progress'
            if not rec.start_datetime:
                rec.start_datetime = fields.Datetime.now()

    def action_complete(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please load / fill in the checklist before completing the inspection.'))
            if rec.odometer_reading and rec.vehicle_id.odometer and rec.odometer_reading < rec.vehicle_id.odometer:
                raise UserError(_(
                    'The odometer reading (%(reading)s) is lower than the last recorded '
                    'odometer of %(vehicle)s (%(last)s). Please check the mileage.',
                    reading=rec.odometer_reading, vehicle=rec.vehicle_id.display_name,
                    last=rec.vehicle_id.odometer))
            if rec.driver_signature and not rec.driver_signature_date:
                rec.driver_signature_date = fields.Datetime.now()
            if rec.mechanic_signature and not rec.mechanic_signature_date:
                rec.mechanic_signature_date = fields.Datetime.now()
            rec.line_ids._flag_worn_tyres()
            rec.end_datetime = fields.Datetime.now()
            rec.state = 'completed'
        self._flag_repeat_defects()
        self._log_odometer()

    def action_approve(self):
        for rec in self:
            if rec.state != 'completed':
                raise UserError(_('Only completed inspections can be approved.'))
            if rec.supervisor_signature and not rec.supervisor_signature_date:
                rec.supervisor_signature_date = fields.Datetime.now()
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })

    def action_return_to_inspector(self):
        """Supervisor sends a completed inspection back for corrections."""
        for rec in self:
            if rec.state != 'completed':
                raise UserError(_('Only completed inspections can be returned to the inspector.'))
            rec.state = 'in_progress'
            rec.message_post(body=_('Inspection returned to the inspector for corrections.'))
            if rec.create_uid:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=rec.create_uid.id,
                    summary=_('Correct inspection %s', rec.name))

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'approved_by_id': False, 'approved_on': False})

    # --- Job cards ---------------------------------------------------------------
    def action_create_maintenance(self):
        """Open the wizard that splits the defects into one job card per job type."""
        self.ensure_one()
        if not self.line_ids.filtered(lambda l: l.result == 'defective' and not l.job_card_id):
            raise UserError(_('All defects of this inspection already have a job card.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Job Cards'),
            'res_model': 'fleet.inspection.job.card.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_inspection_id': self.id},
        }

    @api.model
    def _get_default_service_type(self):
        ServiceType = self.env['fleet.service.type']
        service_type = ServiceType.search([('name', 'ilike', 'Repair')], limit=1) \
            or ServiceType.search([('name', 'ilike', 'Inspection')], limit=1)
        if not service_type:
            service_type = ServiceType.sudo().create({'name': _('Repair'), 'category': 'service'})
        return service_type

    def _create_job_cards(self, lines_by_job_type):
        """Create one job card per (job type -> defect lines) entry.

        :param lines_by_job_type: dict {fleet.inspection.job.type record (may be empty): fleet.inspection.line recordset}
        :return: created fleet.vehicle.log.services recordset
        """
        self.ensure_one()
        Service = self.env['fleet.vehicle.log.services']
        severity_labels = dict(self.env['fleet.inspection.line']._fields['severity'].selection)
        services = Service
        for job_type, lines in lines_by_job_type.items():
            if not lines:
                continue
            if lines.job_card_id:
                raise UserError(_('Some of the selected defects already have a job card.'))
            label = job_type.name if job_type else _('General')
            description_lines = [
                '- %s / %s (%s)%s' % (
                    line.category_id.name, line.item_id.name,
                    severity_labels.get(line.severity),
                    (': %s' % line.comment) if line.comment else '')
                for line in lines
            ]
            vals = {
                'vehicle_id': self.vehicle_id.id,
                'inspection_id': self.id,
                'inspection_job_type_id': job_type.id if job_type else False,
                'inspection_line_ids': [fields.Command.set(lines.ids)],
                'service_type_id': (job_type.service_type_id or self._get_default_service_type()).id,
                'description': _('%(job_type)s defects - inspection %(name)s', job_type=label, name=self.name),
                'notes': _('Defects found during inspection %(name)s:\n%(defects)s',
                           name=self.name, defects='\n'.join(description_lines)),
                'date': fields.Date.context_today(self),
                'service_type': 'inspection_followup',
                'current_mileage': self.odometer_reading,
                'supervisor_id': self.supervisor_id.id,
            }
            if any(l.severity == 'high' for l in lines):
                vals['priority'] = '3'
            elif any(l.severity == 'medium' for l in lines):
                vals['priority'] = '2'
            else:
                vals['priority'] = '1'
            if job_type and job_type.responsible_id:
                vals['technician_id'] = job_type.responsible_id.id
            if job_type and job_type.workshop_id:
                vals['workshop_id'] = job_type.workshop_id.id
            services |= Service.create(vals)
        if services:
            self.message_post(body=_('Job cards created: %s', ', '.join(services.mapped('display_name'))))
        return services

    def action_view_services(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Job Cards'),
            'res_model': 'fleet.vehicle.log.services',
            'view_mode': 'list,form',
            'domain': [('inspection_id', '=', self.id)],
            'context': {'default_inspection_id': self.id, 'default_vehicle_id': self.vehicle_id.id},
        }
        if len(self.service_ids) == 1:
            action.update({'view_mode': 'form', 'res_id': self.service_ids.id})
        return action

    def action_view_previous_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inspections of %s', self.vehicle_id.display_name),
            'res_model': 'fleet.inspection',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.vehicle_id.id)],
        }

    # --- Dashboard -----------------------------------------------------------------
    @api.model
    def _dashboard_overdue_days(self):
        param = self.env['ir.config_parameter'].sudo().get_param('inspection.overdue_days', '7')
        try:
            return max(int(param), 1)
        except ValueError:
            return 7

    @api.model
    def get_dashboard_data(self, days=30):
        """Aggregated figures for the inspection dashboard (client action)."""
        days = max(int(days or 30), 1)
        today = fields.Date.context_today(self)
        date_from = today - timedelta(days=days - 1)
        prev_from = date_from - timedelta(days=days)
        prev_to = date_from - timedelta(days=1)
        Line = self.env['fleet.inspection.line']
        Vehicle = self.env['fleet.vehicle']

        period = [('date', '>=', date_from), ('date', '<=', today), ('state', '!=', 'cancel')]
        previous = [('date', '>=', prev_from), ('date', '<=', prev_to), ('state', '!=', 'cancel')]
        line_period = [('inspection_date', '>=', date_from), ('inspection_date', '<=', today),
                       ('inspection_state', '!=', 'cancel'), ('result', '=', 'defective')]

        total = self.search_count(period)
        total_prev = self.search_count(previous)
        by_result = dict(self._read_group(period, ['result'], ['__count']))
        with_result = sum(by_result.values()) - by_result.get(False, 0)
        pass_rate = round(100.0 * by_result.get('pass', 0) / with_result, 1) if with_result else 0.0
        prev_by_result = dict(self._read_group(previous, ['result'], ['__count']))
        prev_with_result = sum(prev_by_result.values()) - prev_by_result.get(False, 0)
        prev_pass_rate = round(100.0 * prev_by_result.get('pass', 0) / prev_with_result, 1) \
            if prev_with_result else 0.0
        avg_health = self._read_group(period + [('total_items', '>', 0)], [], ['health_score:avg'])[0][0] or 0.0
        avg_duration = self._read_group(period + [('duration', '>', 0)], [], ['duration:avg'])[0][0] or 0.0

        # Fleet coverage: active vehicles inspected in the period
        active_vehicles = Vehicle.search_count([('active', '=', True)])
        inspected_vehicles = len(self._read_group(period, ['vehicle_id'], ['__count']))

        # Open work
        to_approve = self.search_count([('state', '=', 'completed')])
        in_progress = self.search_count([('state', 'in', ('draft', 'in_progress'))])
        awaiting_job = Line.search_count([
            ('result', '=', 'defective'), ('job_card_id', '=', False),
            ('inspection_state', '=', 'approved')])
        open_high = Line.search_count([
            ('result', '=', 'defective'), ('severity', '=', 'high'),
            ('inspection_state', 'in', ('completed', 'approved')),
            '|', ('job_card_id', '=', False), ('job_card_id.state', 'not in', CLOSED_JOB_STATES)])
        repeat_defects = Line.search_count(line_period + [('is_repeat_defect', '=', True)])
        period_defects = Line.search_count(line_period)
        fixed_defects = Line.search_count(line_period + [('repair_state', '=', 'fixed')])
        open_jobs = 0
        Service = self.env['fleet.vehicle.log.services']
        if Service.has_access('read'):
            open_jobs = Service.search_count([
                ('inspection_id', '!=', False), ('state', 'not in', CLOSED_JOB_STATES)])

        # Trend: daily up to 31 days, weekly beyond
        granularity = 'day' if days <= 31 else ('week' if days <= 120 else 'month')

        def bucket_of(day):
            if granularity == 'day':
                return day
            if granularity == 'week':
                return day - timedelta(days=day.weekday())
            return day.replace(day=1)

        buckets = []
        cursor = date_from
        while cursor <= today:
            key = bucket_of(cursor)
            if key not in buckets:
                buckets.append(key)
            cursor += timedelta(days=1)
        trend = {key: {'pass': 0, 'pass_defects': 0, 'fail': 0} for key in buckets}
        for day, result, count in self._read_group(period, ['date:day', 'result'], ['__count']):
            key = bucket_of(day)
            if key in trend and result in trend[key]:
                trend[key][result] += count
        if granularity == 'day':
            labels = [b.strftime('%d %b') for b in buckets]
        elif granularity == 'week':
            labels = [_('Wk %s', b.strftime('%d %b')) for b in buckets]
        else:
            labels = [b.strftime('%b %Y') for b in buckets]
        trend_data = {
            'labels': labels,
            'starts': [fields.Date.to_string(b) for b in buckets],
            'granularity': granularity,
            'series': {res: [trend[b][res] for b in buckets] for res in ('pass', 'pass_defects', 'fail')},
        }

        # Defects by category, split by severity
        cat_groups = Line._read_group(line_period, ['category_id', 'severity'], ['__count'])
        cat_totals = {}
        for category, severity, count in cat_groups:
            entry = cat_totals.setdefault(category, {'low': 0, 'medium': 0, 'high': 0})
            entry[severity or 'low'] += count
        top_categories = sorted(cat_totals.items(), key=lambda kv: -sum(kv[1].values()))[:10]
        defects_by_category = [{
            'id': cat.id, 'name': cat.display_name,
            'low': v['low'], 'medium': v['medium'], 'high': v['high'],
            'total': sum(v.values()),
        } for cat, v in top_categories]

        job_type_groups = Line._read_group(line_period, ['job_type_id'], ['__count'], order='__count desc')
        defects_by_job_type = [{
            'id': jt.id, 'name': jt.display_name if jt else _('Unassigned'), 'count': count,
        } for jt, count in job_type_groups]

        vehicle_groups = Line._read_group(line_period, ['vehicle_id'], ['__count'],
                                          order='__count desc', limit=10)
        defects_by_vehicle = [{
            'id': v.id, 'name': v.display_name, 'count': count,
        } for v, count in vehicle_groups]

        item_groups = Line._read_group(line_period, ['item_id'], ['__count'], order='__count desc', limit=8)
        top_items = [{
            'id': item.id, 'name': item.display_name, 'category': item.category_id.display_name,
            'count': count,
        } for item, count in item_groups]

        # Mechanic performance
        mech_groups = self._read_group(
            period, ['mechanic_id'], ['__count', 'defective_count:sum', 'duration:avg', 'health_score:avg'],
            order='__count desc', limit=8)
        mechanics = [{
            'id': mech.id, 'name': mech.display_name, 'count': count,
            'defects': defects or 0, 'avg_duration': round(dur or 0.0, 2),
            'avg_health': round(health or 0.0, 1),
        } for mech, count, defects, dur, health in mech_groups]

        # Vehicles overdue for inspection
        overdue_days = self._dashboard_overdue_days()
        overdue_limit = today - timedelta(days=overdue_days)
        last_dates = dict(self._read_group(
            [('state', '!=', 'cancel')], ['vehicle_id'], ['date:max']))
        overdue = []
        for vehicle in Vehicle.search([('active', '=', True)]):
            last = last_dates.get(vehicle)
            if not last or last < overdue_limit:
                overdue.append({
                    'id': vehicle.id, 'name': vehicle.display_name,
                    'plate': vehicle.license_plate or '',
                    'last_date': fields.Date.to_string(last) if last else False,
                    'days': (today - last).days if last else None,
                })
        overdue.sort(key=lambda v: -(v['days'] if v['days'] is not None else 10 ** 6))

        failed = self.search(period + [('result', '=', 'fail')], limit=8)
        recent_failed = [{
            'id': rec.id, 'name': rec.name, 'vehicle': rec.vehicle_id.display_name,
            'date': fields.Date.to_string(rec.date), 'high': rec.high_defect_count,
            'defects': rec.defective_count, 'state': rec.state,
            'job_card_status': rec.job_card_status,
        } for rec in failed]

        return {
            'period': {'days': days, 'date_from': fields.Date.to_string(date_from),
                       'date_to': fields.Date.to_string(today)},
            'kpi': {
                'total': total, 'total_prev': total_prev,
                'pass': by_result.get('pass', 0),
                'pass_defects': by_result.get('pass_defects', 0),
                'fail': by_result.get('fail', 0),
                'pass_rate': pass_rate, 'pass_rate_prev': prev_pass_rate,
                'avg_health': round(avg_health, 1),
                'avg_duration': round(avg_duration, 2),
                'active_vehicles': active_vehicles,
                'inspected_vehicles': inspected_vehicles,
                'coverage': round(100.0 * inspected_vehicles / active_vehicles, 1) if active_vehicles else 0.0,
                'to_approve': to_approve,
                'in_progress': in_progress,
                'awaiting_job': awaiting_job,
                'open_high': open_high,
                'open_jobs': open_jobs,
                'repeat_defects': repeat_defects,
                'period_defects': period_defects,
                'fixed_defects': fixed_defects,
                'fixed_rate': round(100.0 * fixed_defects / period_defects, 1) if period_defects else 0.0,
                'overdue': len(overdue),
                'overdue_days': overdue_days,
            },
            'trend': trend_data,
            'defects_by_category': defects_by_category,
            'defects_by_job_type': defects_by_job_type,
            'defects_by_vehicle': defects_by_vehicle,
            'top_items': top_items,
            'mechanics': mechanics,
            'overdue': overdue[:10],
            'overdue_ids': [v['id'] for v in overdue],
            'recent_failed': recent_failed,
        }
