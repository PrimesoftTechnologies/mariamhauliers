# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .fleet_inspection import CLOSED_JOB_STATES
from .fleet_job_material_request import OPEN_MR_STATES


def _period_buckets(date_from, date_to, days):
    """Return (granularity, bucket_of function, ordered bucket starts)."""
    granularity = 'day' if days <= 31 else ('week' if days <= 120 else 'month')

    def bucket_of(day):
        if granularity == 'day':
            return day
        if granularity == 'week':
            return day - timedelta(days=day.weekday())
        return day.replace(day=1)

    buckets = []
    cursor = date_from
    while cursor <= date_to:
        key = bucket_of(cursor)
        if key not in buckets:
            buckets.append(key)
        cursor += timedelta(days=1)
    return granularity, bucket_of, buckets


class FleetVehicleLogServices(models.Model):
    """The Fleet service log is used as the workshop Job Card."""
    _inherit = 'fleet.vehicle.log.services'
    _description = 'Fleet Job Card'

    # --- Inspection link -----------------------------------------------------------
    inspection_id = fields.Many2one('fleet.inspection', string='Source Inspection', readonly=True, index=True)
    inspection_job_type_id = fields.Many2one('fleet.inspection.job.type', string='Job Type', index=True)
    inspection_line_ids = fields.One2many('fleet.inspection.line', 'job_card_id', string='Inspection Defects')
    inspection_defect_count = fields.Integer(compute='_compute_inspection_defect_count')

    # --- Job card ------------------------------------------------------------------
    job_number = fields.Char(string='Job Number', copy=False, readonly=True, default=lambda self: _('New'))
    driver_id = fields.Many2one(related='vehicle_id.driver_id', store=True, readonly=True)
    current_mileage = fields.Float(string='Current Mileage')
    workshop_id = fields.Many2one('fleet.workshop', string='Workshop',
                                  default=lambda self: self.env['fleet.workshop']._get_default_workshop())
    service_type = fields.Selection([
        ('repair', 'Repair'),
        ('preventive', 'Preventive Maintenance'),
        ('accident', 'Accident Repair'),
        ('inspection_followup', 'Inspection Follow-up'),
        ('tyre', 'Tyre Service'),
        ('other', 'Other'),
    ], default='repair', string='Service Type')
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], default='1', string='Priority')

    technician_id = fields.Many2one('hr.employee', string='Assigned Technician', tracking=True)
    supervisor_id = fields.Many2one('hr.employee', string='Workshop Supervisor')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_approval', 'Waiting Approval'),
        ('approved', 'Approved'),
        ('assigned', 'Assigned'),
        ('waiting_parts', 'Waiting Parts'),
        ('parts_ready', 'Parts Ready'),
        ('in_progress', 'In Progress'),
        ('quality_check', 'Quality Check'),
        ('completed', 'Completed'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)

    start_date = fields.Datetime(string='Start Date', copy=False)
    completion_date = fields.Datetime(string='Completion Date', copy=False)
    planned_end_date = fields.Datetime(string='Promised Date', help='Date the vehicle must be back in service.')
    approved_by_id = fields.Many2one('res.users', string='Approved By', copy=False, readonly=True)
    approved_on = fields.Datetime(copy=False, readonly=True)
    closed_by_id = fields.Many2one('res.users', string='Closed By', copy=False, readonly=True)
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue')
    turnaround_hours = fields.Float(string='Turnaround (hrs)', compute='_compute_turnaround', store=True,
                                    aggregator='avg', help='From job card creation to completion.')
    downtime_days = fields.Float(string='Vehicle Downtime (days)', compute='_compute_turnaround', store=True,
                                 aggregator='avg', help='From the inspection (or job date) to completion.')

    job_line_ids = fields.One2many('fleet.job.card.line', 'job_id', string='Repair Tasks / Defects')
    task_progress = fields.Float(string='Tasks Done (%)', compute='_compute_task_progress', store=True)
    material_request_ids = fields.One2many('fleet.job.material.request', 'job_id', string='Material Requests')
    material_request_count = fields.Integer(compute='_compute_material_request_count')
    material_state = fields.Selection([
        ('none', 'No Materials'),
        ('draft', 'Request in Draft'),
        ('to_approve', 'To Approve'),
        ('waiting', 'Waiting Stock / Purchase'),
        ('ready', 'Ready to Issue'),
        ('issued', 'Issued'),
    ], string='Materials', compute='_compute_material_state', store=True)
    pending_fitment_count = fields.Integer(string='Parts to Fit', compute='_compute_pending_fitment')
    labour_line_ids = fields.One2many('fleet.job.labour.line', 'job_id', string='Labour')
    labour_hours = fields.Float(compute='_compute_costs', store=True)
    installed_part_ids = fields.One2many('fleet.vehicle.installed.part', 'job_id', string='Fitted Parts')
    removed_part_ids = fields.One2many('fleet.vehicle.installed.part', 'removal_job_id', string='Removed Parts')
    approval_ids = fields.One2many('fleet.job.approval', 'job_id', string='Approval Log')

    # --- Outside / vendor service --------------------------------------------
    outside_service = fields.Boolean(string='Outsourced')
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    vendor_quotation_ref = fields.Char(string='Quotation Ref.')
    vendor_po_id = fields.Many2one('purchase.order', string='Vendor PO')
    vendor_bill_id = fields.Many2one('account.move', string='Vendor Bill')
    outside_cost = fields.Float(string='Outside Service Cost')

    # --- Quality check ---------------------------------------------------------
    quality_checked_by = fields.Many2one('hr.employee', string='Quality Checked By')
    quality_check_date = fields.Datetime(string='Quality Check Date')
    quality_result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
    ], string='Quality Result')
    quality_notes = fields.Text(string='Quality Notes')
    road_test_done = fields.Boolean(string='Road Test Done')

    # --- Sign off ---------------------------------------------------------------
    mechanic_signature = fields.Binary(string='Mechanic Signature')
    supervisor_signature = fields.Binary(string='Supervisor Signature')
    remarks = fields.Text(string='Remarks')

    # --- Costing --------------------------------------------------------------
    estimated_cost = fields.Float(compute='_compute_costs', store=True)
    labour_cost = fields.Float(compute='_compute_costs', store=True)
    parts_cost = fields.Float(compute='_compute_costs', store=True)
    actual_cost = fields.Float(compute='_compute_costs', store=True)
    requires_manager_approval = fields.Boolean(compute='_compute_requires_manager_approval')

    # ------------------------------------------------------------------ computes
    @api.depends('inspection_job_type_id', 'job_number')
    def _compute_display_name(self):
        super()._compute_display_name()
        for rec in self:
            if rec.job_number and rec.job_number != _('New'):
                rec.display_name = rec.job_number
            if rec.inspection_job_type_id:
                rec.display_name = '%s (%s)' % (rec.display_name, rec.inspection_job_type_id.name)

    @api.depends('inspection_line_ids')
    def _compute_inspection_defect_count(self):
        for rec in self:
            rec.inspection_defect_count = len(rec.inspection_line_ids)

    @api.depends('job_line_ids.estimated_cost', 'labour_line_ids.amount', 'labour_line_ids.hours',
                 'material_request_ids.total_used_cost', 'outside_cost')
    def _compute_costs(self):
        for rec in self:
            rec.estimated_cost = sum(rec.job_line_ids.mapped('estimated_cost'))
            rec.labour_cost = sum(rec.labour_line_ids.mapped('amount'))
            rec.labour_hours = sum(rec.labour_line_ids.mapped('hours'))
            rec.parts_cost = sum(rec.material_request_ids.mapped('total_used_cost'))
            rec.actual_cost = rec.labour_cost + rec.parts_cost + (rec.outside_cost or 0.0)

    @api.depends('job_line_ids.completed')
    def _compute_task_progress(self):
        for rec in self:
            total = len(rec.job_line_ids)
            rec.task_progress = (100.0 * len(rec.job_line_ids.filtered('completed')) / total) if total else 0.0

    def _compute_material_request_count(self):
        for rec in self:
            rec.material_request_count = len(rec.material_request_ids)

    @api.depends('material_request_ids.state')
    def _compute_material_state(self):
        for rec in self:
            states = set(rec.material_request_ids.mapped('state')) - {'rejected', 'cancel'}
            if not states:
                rec.material_state = 'none'
            elif 'submitted' in states:
                rec.material_state = 'to_approve'
            elif states & {'approved', 'waiting_stock'}:
                rec.material_state = 'waiting'
            elif 'ready' in states:
                rec.material_state = 'ready'
            elif 'draft' in states:
                rec.material_state = 'draft'
            else:
                rec.material_state = 'issued'

    def _pending_fitment_lines(self):
        """Issued serialised fleet parts (tyres, batteries) not fitted yet."""
        return self.material_request_ids.filtered(lambda m: m.state in ('issued', 'done')).line_ids.filtered(
            lambda l: l.is_serial and l.fleet_part_type and l.pending_fit_lot_ids)

    def _compute_pending_fitment(self):
        for rec in self:
            pending = 0
            for line in rec._pending_fitment_lines():
                fitted = len(line.issued_lot_ids) - len(line.pending_fit_lot_ids)
                # serials recorded as not used (used qty lowered) are returned, not fitted
                pending += max(min(len(line.pending_fit_lot_ids), int(round(line.used_qty)) - fitted), 0)
            rec.pending_fitment_count = pending

    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(rec.planned_end_date and rec.planned_end_date < now
                                  and rec.state not in CLOSED_JOB_STATES)

    def _search_is_overdue(self, operator, value):
        domain = [('planned_end_date', '<', fields.Datetime.now()), ('state', 'not in', CLOSED_JOB_STATES)]
        if (operator == '=' and value) or (operator == '!=' and not value):
            return domain
        return ['!', '&'] + domain

    @api.depends('completion_date', 'create_date', 'date', 'inspection_id.date')
    def _compute_turnaround(self):
        for rec in self:
            if rec.completion_date and rec.create_date:
                rec.turnaround_hours = max((rec.completion_date - rec.create_date).total_seconds() / 3600.0, 0.0)
                start = rec.inspection_id.date or rec.date or rec.create_date.date()
                rec.downtime_days = max((rec.completion_date.date() - start).days, 0)
            else:
                rec.turnaround_hours = 0.0
                rec.downtime_days = 0.0

    def _manager_approval_amount(self):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(
                'inspection.job_manager_approval_amount', '0') or 0.0)
        except ValueError:
            return 0.0

    @api.depends('estimated_cost')
    def _compute_requires_manager_approval(self):
        limit = self._manager_approval_amount()
        for rec in self:
            rec.requires_manager_approval = bool(limit and rec.estimated_cost > limit)

    # ------------------------------------------------------------------ CRUD
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('job_number', _('New')) == _('New'):
                vals['job_number'] = self.env['ir.sequence'].next_by_code('fleet.job.card') or _('New')
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if vals.get('inspection_id') and not vals.get('job_line_ids'):
                rec._load_lines_from_inspection()
        return records

    # --- Bring defect lines over from the source inspection --------------------
    def _load_lines_from_inspection(self):
        """Create repair tasks for the defects of this job card. A job card created
        from the wizard only gets its own defects (one job card per job type)."""
        self.ensure_one()
        if not self.inspection_id:
            return
        defects = self.inspection_line_ids
        if not defects:
            defects = self.inspection_id.line_ids.filtered(
                lambda l: l.result == 'defective' and not l.job_card_id)
            defects.write({'job_card_id': self.id})
        defects -= self.job_line_ids.inspection_line_id
        sequence = max(self.job_line_ids.mapped('sequence') or [0]) + 10
        commands = []
        for line in defects:
            commands.append(fields.Command.create({
                'category_id': line.category_id.id,
                'problem': line.item_id.name,
                'inspection_line_id': line.id,
                'severity': line.severity or 'medium',
                'description': line.comment or '',
                'sequence': sequence,
            }))
            sequence += 10
        if commands:
            self.job_line_ids = commands

    def action_load_from_inspection(self):
        for rec in self:
            rec._load_lines_from_inspection()

    # ------------------------------------------------------------------ helpers
    def _check_group(self, xmlid, message):
        if not self.env.user.has_group(xmlid):
            raise UserError(message)

    def _check_state(self, states, action):
        for rec in self:
            if rec.state not in states:
                raise UserError(_('%(job)s: cannot %(action)s a job card in state "%(state)s".',
                                  job=rec.display_name, action=action,
                                  state=dict(self._fields['state'].selection).get(rec.state)))

    def _log(self, stage, state='approved', comment=False, approval_type='job_card'):
        Approval = self.env['fleet.job.approval']
        for rec in self:
            Approval._log(rec, approval_type, stage, state=state, comment=comment)

    def _notify(self, user, summary, note=False):
        if user:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary, note=note)

    def _update_material_state(self):
        """Move the job between Waiting Parts / Parts Ready as its material requests progress."""
        for job in self.filtered(lambda j: j.state in ('assigned', 'waiting_parts', 'parts_ready')):
            requests = job.material_request_ids.filtered(lambda m: m.state not in ('draft', 'rejected', 'cancel'))
            if not requests:
                continue
            if any(m.state in ('submitted', 'approved', 'waiting_stock') for m in requests):
                new_state = 'waiting_parts'
            else:
                new_state = 'parts_ready'
            if new_state != job.state:
                job.state = new_state
                if new_state == 'parts_ready' and job.technician_id.user_id:
                    job._notify(job.technician_id.user_id, _('Parts ready for %s', job.display_name))

    # ------------------------------------------------------------------ workflow
    def action_submit(self):
        self._check_state(('draft',), _('submit'))
        for rec in self:
            if not rec.job_line_ids:
                raise UserError(_('Add at least one repair task / defect line before submitting.'))
            rec.state = 'waiting_approval'
            rec._log(_('Submitted'))
            approver = rec.supervisor_id.user_id or rec.workshop_id.manager_id.user_id
            rec._notify(approver, _('Approve job card %s', rec.display_name))

    def action_approve(self):
        self._check_group('inspection.group_workshop_supervisor',
                          _('Only a Workshop Supervisor can approve job cards.'))
        self._check_state(('waiting_approval',), _('approve'))
        is_manager = self.env.user.has_group('inspection.group_inspection_manager')
        for rec in self:
            if rec.requires_manager_approval and not is_manager:
                raise UserError(_('%(job)s is estimated at %(amount).2f, above the approval limit of '
                                  '%(limit).2f: a Fleet Manager must approve it.',
                                  job=rec.display_name, amount=rec.estimated_cost,
                                  limit=rec._manager_approval_amount()))
            rec.write({'state': 'approved', 'approved_by_id': self.env.uid, 'approved_on': fields.Datetime.now()})
            rec._log(_('Fleet Manager') if rec.requires_manager_approval else _('Workshop Supervisor'))
            rec.activity_feedback(['mail.mail_activity_data_todo'])
            if rec.technician_id:
                rec.action_assign()

    def action_reject(self):
        self._check_group('inspection.group_workshop_supervisor',
                          _('Only a Workshop Supervisor can reject job cards.'))
        self._check_state(('waiting_approval',), _('reject'))
        for rec in self:
            rec.state = 'draft'
            rec._log(_('Workshop Supervisor'), state='rejected')
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            rec._notify(rec.create_uid, _('Job card %s was rejected', rec.display_name))

    def action_assign(self):
        self._check_state(('approved',), _('assign'))
        for rec in self:
            if not rec.technician_id:
                raise UserError(_('Please select a Technician before assigning the job.'))
            rec.state = 'assigned'
            rec._notify(rec.technician_id.user_id, _('Job card %s assigned to you', rec.display_name))
        self._update_material_state()

    def action_mark_waiting_parts(self):
        self._check_state(('assigned', 'parts_ready', 'in_progress'), _('set waiting parts on'))
        self.write({'state': 'waiting_parts'})

    def action_mark_parts_ready(self):
        self._check_state(('waiting_parts',), _('set parts ready on'))
        self.write({'state': 'parts_ready'})

    def action_start_repair(self):
        self._check_state(('assigned', 'waiting_parts', 'parts_ready'), _('start'))
        for rec in self:
            if not rec.technician_id:
                raise UserError(_('Please select a Technician before starting the repair.'))
            if not rec.start_date:
                rec.start_date = fields.Datetime.now()
            rec.state = 'in_progress'

    def _check_ready_for_quality(self):
        for rec in self:
            open_tasks = rec.job_line_ids.filtered(lambda l: not l.completed)
            if open_tasks:
                raise UserError(_('%(job)s: mark every repair task as completed first:\n%(tasks)s',
                                  job=rec.display_name, tasks='\n'.join('- %s' % t.problem for t in open_tasks)))
            open_requests = rec.material_request_ids.filtered(lambda m: m.state in OPEN_MR_STATES)
            if open_requests:
                raise UserError(_('%(job)s: these material requests are not issued yet: %(mr)s. '
                                  'Issue or cancel them first.',
                                  job=rec.display_name, mr=', '.join(open_requests.mapped('name'))))
            if rec.pending_fitment_count:
                raise UserError(_('%(job)s: %(count)s issued serialised part(s) (tyres, batteries...) are '
                                  'not fitted yet. Use "Record Fitment", or record them as not used.',
                                  job=rec.display_name, count=rec.pending_fitment_count))

    def action_send_quality_check(self):
        self._check_state(('in_progress',), _('send to quality check'))
        self._check_ready_for_quality()
        self.write({'state': 'quality_check'})
        for rec in self:
            rec._notify(rec.supervisor_id.user_id or rec.workshop_id.manager_id.user_id,
                        _('Quality check of %s', rec.display_name))

    def action_quality_pass(self):
        self._check_group('inspection.group_workshop_supervisor',
                          _('Only a Workshop Supervisor can perform the quality check.'))
        self._check_state(('quality_check',), _('pass'))
        for rec in self:
            rec.write({
                'quality_result': 'pass',
                'quality_check_date': fields.Datetime.now(),
                'quality_checked_by': (rec.quality_checked_by or rec.supervisor_id
                                       or self.env.user.employee_id).id,
            })
            rec._log(_('Quality Check'), comment=rec.quality_notes, approval_type='quality')
        self._action_close()

    def action_quality_fail(self):
        self._check_group('inspection.group_workshop_supervisor',
                          _('Only a Workshop Supervisor can perform the quality check.'))
        self._check_state(('quality_check',), _('fail'))
        for rec in self:
            rec.write({'quality_result': 'fail', 'quality_check_date': fields.Datetime.now(),
                       'state': 'in_progress'})
            rec._log(_('Quality Check'), state='rejected', comment=rec.quality_notes, approval_type='quality')
            rec._notify(rec.technician_id.user_id, _('Quality check failed on %s', rec.display_name),
                        note=rec.quality_notes)

    def _action_close(self):
        """Close the job card: complete the issued material requests (unused parts are
        returned to stock), freeze the cost and report back to the inspection."""
        for rec in self:
            rec.material_request_ids.filtered(lambda m: m.state == 'issued').action_done()
            rec.write({
                'state': 'completed',
                'completion_date': fields.Datetime.now(),
                'closed_by_id': self.env.uid,
            })
            rec.amount = rec.actual_cost
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            if rec.inspection_id:
                rec.inspection_id.sudo().message_post(body=_(
                    'Job card %(job)s closed: %(count)s defect(s) repaired.',
                    job=rec.display_name, count=len(rec.inspection_line_ids)))

    def action_cancel(self):
        self._check_state(('draft', 'waiting_approval', 'approved', 'assigned', 'waiting_parts',
                           'parts_ready', 'in_progress', 'quality_check'), _('cancel'))
        for rec in self:
            rec.material_request_ids.filtered(lambda m: m.state in OPEN_MR_STATES).action_cancel()
            if rec.material_request_ids.filtered(lambda m: m.state == 'issued'):
                raise UserError(_('%s has issued materials: record their usage first.', rec.display_name))
            rec.state = 'cancel'
            rec.activity_unlink(['mail.mail_activity_data_todo'])

    def action_reset_to_draft(self):
        self._check_group('inspection.group_workshop_supervisor',
                          _('Only a Workshop Supervisor can reset job cards.'))
        self._check_state(('cancel',), _('reset'))
        self.write({'state': 'draft', 'approved_by_id': False, 'approved_on': False, 'quality_result': False})

    # ------------------------------------------------------------------ navigation
    def action_view_material_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Material Requests'),
            'res_model': 'fleet.job.material.request',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }

    def action_new_material_request(self):
        self.ensure_one()
        if self.state in CLOSED_JOB_STATES:
            raise UserError(_('The job card is closed.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Material Request'),
            'res_model': 'fleet.job.material.request',
            'view_mode': 'form',
            'context': {'default_job_id': self.id},
        }

    def action_record_fitment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Fitment'),
            'res_model': 'fleet.part.fitment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id},
        }

    def action_view_fitted_parts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Parts fitted / removed'),
            'res_model': 'fleet.vehicle.installed.part',
            'view_mode': 'list,form',
            'domain': ['|', ('job_id', '=', self.id), ('removal_job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }

    def action_open_inspection(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.inspection',
            'view_mode': 'form',
            'res_id': self.inspection_id.id,
        }

    # ------------------------------------------------------------------ dashboard
    @api.model
    def get_workshop_dashboard_data(self, days=30):
        """Figures for the Workshop and Stores & Tyres tabs of the dashboard."""
        if not self.env.user.has_group('inspection.group_inspection_inspector'):
            return {'allowed': False}
        days = max(int(days or 30), 1)
        today = fields.Date.context_today(self)
        date_from = today - timedelta(days=days - 1)
        dt_from = datetime.combine(date_from, time.min)
        dt_to = datetime.combine(today, time.max)
        now = fields.Datetime.now()
        Labour = self.env['fleet.job.labour.line']
        Request = self.env['fleet.job.material.request']
        RequestLine = self.env['fleet.job.material.request.line']
        Part = self.env['fleet.vehicle.installed.part']
        Lot = self.env['stock.lot']

        open_domain = [('state', 'not in', CLOSED_JOB_STATES), ('job_number', '!=', False)]
        done_domain = [('state', '=', 'completed'), ('completion_date', '>=', dt_from), ('completion_date', '<=', dt_to)]
        state_labels = dict(self._fields['state'].selection)
        open_by_state = dict(self._read_group(open_domain, ['state'], ['__count']))
        sums = self._read_group(done_domain, [], [
            'actual_cost:sum', 'labour_cost:sum', 'parts_cost:sum', 'outside_cost:sum',
            'turnaround_hours:avg', 'downtime_days:avg', '__count'])[0]
        total_cost, labour_cost, parts_cost, outside_cost, avg_tat, avg_downtime, completed = sums

        # Cost trend by completion date, split labour / parts / outside
        granularity, bucket_of, buckets = _period_buckets(date_from, today, days)
        trend = {b: {'labour': 0.0, 'parts': 0.0, 'outside': 0.0} for b in buckets}
        for day, labour, parts, outside in self._read_group(
                done_domain, ['completion_date:day'], ['labour_cost:sum', 'parts_cost:sum', 'outside_cost:sum']):
            key = bucket_of(day.date() if isinstance(day, datetime) else day)
            if key in trend:
                trend[key]['labour'] += labour or 0.0
                trend[key]['parts'] += parts or 0.0
                trend[key]['outside'] += outside or 0.0
        if granularity == 'day':
            labels = [b.strftime('%d %b') for b in buckets]
        elif granularity == 'week':
            labels = [_('Wk %s', b.strftime('%d %b')) for b in buckets]
        else:
            labels = [b.strftime('%b %Y') for b in buckets]

        cost_by_vehicle = [{
            'id': vehicle.id, 'name': vehicle.display_name, 'count': count, 'cost': round(cost or 0.0, 2),
        } for vehicle, count, cost in self._read_group(
            done_domain, ['vehicle_id'], ['__count', 'actual_cost:sum'], order='actual_cost:sum desc', limit=10)]

        by_job_type = [{
            'id': jt.id, 'name': jt.display_name if jt else _('Unassigned'), 'count': count,
            'cost': round(cost or 0.0, 2),
        } for jt, count, cost in self._read_group(
            done_domain, ['inspection_job_type_id'], ['__count', 'actual_cost:sum'], order='__count desc')]

        technicians = [{
            'id': emp.id, 'name': emp.display_name, 'hours': round(hours or 0.0, 1),
            'amount': round(amount or 0.0, 2), 'jobs': len(set(jobs)) if jobs else 0,
        } for emp, hours, amount, jobs in Labour._read_group(
            [('date', '>=', date_from), ('date', '<=', today)], ['employee_id'],
            ['hours:sum', 'amount:sum', 'job_id:array_agg'], order='hours:sum desc', limit=8)]

        oldest = self.search(open_domain, order='create_date asc', limit=10)
        oldest_jobs = [{
            'id': job.id, 'name': job.display_name, 'vehicle': job.vehicle_id.display_name,
            'state': job.state, 'state_label': state_labels.get(job.state),
            'age': (now - job.create_date).days if job.create_date else 0,
            'overdue': job.is_overdue, 'material_state': job.material_state,
        } for job in oldest]

        # ---- Stores
        mr_by_state = dict(Request._read_group(
            [('state', 'in', ('submitted', 'approved', 'waiting_stock', 'ready', 'issued'))], ['state'], ['__count']))
        shortage_lines = RequestLine.search_count([
            ('open_purchase_qty', '>', 0), ('request_state', 'in', ('approved', 'waiting_stock', 'ready'))])
        open_rfq = 0
        PurchaseOrder = self.env['purchase.order']
        if PurchaseOrder.has_access('read'):
            open_rfq = PurchaseOrder.search_count([
                ('workshop_material_request_id', '!=', False), ('state', 'in', ('draft', 'sent', 'to approve'))])
        top_parts = [{
            'id': product.id, 'name': product.display_name, 'qty': round(qty or 0.0, 2),
            'cost': round(cost or 0.0, 2),
        } for product, qty, cost in RequestLine._read_group(
            [('request_state', 'in', ('issued', 'done')), ('date', '>=', dt_from), ('date', '<=', dt_to)],
            ['product_id'], ['used_qty:sum', 'consumed_cost:sum'], order='consumed_cost:sum desc', limit=8)]

        # ---- Tyres
        tyre_status = dict(Lot._read_group([('fleet_part_type', '=', 'tyre')], ['fleet_status'], ['__count']))
        wear_pct = self.env['ir.config_parameter'].sudo().get_param('inspection.tyre_wear_warning_pct', '90')
        try:
            wear_pct = float(wear_pct)
        except ValueError:
            wear_pct = 90.0
        due = []
        for lot in Lot.search([('fleet_part_type', '=', 'tyre'), ('fleet_status', '=', 'installed')]):
            if lot._fleet_needs_replacement(wear_pct):
                due.append({
                    'id': lot.id, 'name': lot.name, 'product': lot.product_id.display_name,
                    'vehicle': lot.fleet_vehicle_id.display_name or '', 'vehicle_id': lot.fleet_vehicle_id.id,
                    'position': lot.fleet_position_id.code or '', 'km': round(lot.fleet_km_total),
                    'wear': round(lot.fleet_wear_pct), 'tread': lot.fleet_last_tread_depth,
                })
        due.sort(key=lambda d: -d['wear'])
        removal_labels = dict(Part._fields['removal_reason'].selection)
        removal_domain = [('status', '=', 'removed'), ('remove_date', '>=', date_from),
                          ('remove_date', '<=', today), ('part_type', '=', 'tyre')]
        removals = [{
            'id': reason or False, 'name': removal_labels.get(reason, _('Undefined')), 'count': count,
        } for reason, count in Part._read_group(removal_domain, ['removal_reason'], ['__count'],
                                                order='__count desc')]
        cost_per_km = []
        for product, km, cost, count in Part._read_group(
                [('status', '=', 'removed'), ('part_type', '=', 'tyre'), ('mileage_covered', '>', 0)],
                ['product_id'], ['mileage_covered:sum', 'cost:sum', '__count'], order='__count desc', limit=8):
            cost_per_km.append({
                'id': product.id, 'name': product.display_name, 'count': count, 'avg_km': round(km / count),
                'cost_per_km': round(cost / km, 4) if km else 0.0,
            })

        return {
            'allowed': True,
            'is_supervisor': self.env.user.has_group('inspection.group_workshop_supervisor'),
            'period': {'days': days, 'date_from': fields.Date.to_string(date_from),
                       'date_to': fields.Date.to_string(today),
                       'dt_from': fields.Datetime.to_string(dt_from), 'dt_to': fields.Datetime.to_string(dt_to)},
            'kpi': {
                'open_jobs': sum(open_by_state.values()),
                'waiting_approval': open_by_state.get('waiting_approval', 0),
                'waiting_parts': open_by_state.get('waiting_parts', 0),
                'in_progress': open_by_state.get('in_progress', 0),
                'quality_check': open_by_state.get('quality_check', 0),
                'overdue_jobs': self.search_count(open_domain + [('planned_end_date', '<', now)]),
                'completed': completed or 0,
                'total_cost': round(total_cost or 0.0, 2),
                'labour_cost': round(labour_cost or 0.0, 2),
                'parts_cost': round(parts_cost or 0.0, 2),
                'outside_cost': round(outside_cost or 0.0, 2),
                'avg_tat': round(avg_tat or 0.0, 1),
                'avg_downtime': round(avg_downtime or 0.0, 1),
                'mr_to_approve': mr_by_state.get('submitted', 0),
                'mr_waiting': mr_by_state.get('waiting_stock', 0) + mr_by_state.get('approved', 0),
                'mr_ready': mr_by_state.get('ready', 0),
                'mr_issued': mr_by_state.get('issued', 0),
                'shortage_lines': shortage_lines,
                'open_rfq': open_rfq,
                'tyres_fitted': tyre_status.get('installed', 0),
                'tyres_in_stock': tyre_status.get('in_stock', 0),
                'tyres_retread': tyre_status.get('retread', 0),
                'tyres_due': len(due),
                'wear_pct': wear_pct,
            },
            'jobs_by_state': [{'id': state, 'name': state_labels.get(state), 'count': open_by_state.get(state, 0)}
                              for state, _label in self._fields['state'].selection
                              if state not in CLOSED_JOB_STATES],
            'cost_trend': {
                'labels': labels,
                'starts': [fields.Date.to_string(b) for b in buckets],
                'series': {key: [round(trend[b][key], 2) for b in buckets] for key in ('labour', 'parts', 'outside')},
            },
            'cost_by_vehicle': cost_by_vehicle,
            'by_job_type': by_job_type,
            'technicians': technicians,
            'oldest_jobs': oldest_jobs,
            'top_parts': top_parts,
            'tyres_due': due[:10],
            'tyres_due_ids': [d['id'] for d in due],
            'tyre_removals': removals,
            'tyre_cost_per_km': cost_per_km,
        }
