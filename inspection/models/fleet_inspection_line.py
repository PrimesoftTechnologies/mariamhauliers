# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class FleetInspectionLine(models.Model):
    _name = 'fleet.inspection.line'
    _description = 'Fleet Inspection Checklist Line'
    _order = 'category_id, sequence, id'

    inspection_id = fields.Many2one('fleet.inspection', required=True, ondelete='cascade', index=True)
    category_id = fields.Many2one('fleet.inspection.category', string='Category', required=True)
    item_id = fields.Many2one('fleet.inspection.item', string='Particulars', required=True)
    sequence = fields.Integer(default=10)

    result = fields.Selection([
        ('good', 'Good'),
        ('defective', 'Defective'),
        ('na', 'N/A'),
    ], default='good', required=True)

    severity = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], default='low', string='Severity')

    comment = fields.Char(string='Comment')
    photo = fields.Binary(string='Photo', attachment=True)

    # --- Tyres / serialised parts -------------------------------------------------
    position_id = fields.Many2one(related='item_id.position_id', store=True, string='Position')
    lot_id = fields.Many2one(
        'stock.lot', string='Serial No.', compute='_compute_lot_id', store=True, readonly=False,
        help='Serial number fitted at this position when the inspection was made.')
    tread_depth = fields.Float(string='Tread (mm)', digits=(16, 1))
    pressure = fields.Float(string='Pressure (psi)', digits=(16, 1))
    below_min_tread = fields.Boolean(compute='_compute_below_min_tread', store=True)

    # --- Job card routing -----------------------------------------------------
    job_type_id = fields.Many2one(
        'fleet.inspection.job.type', string='Job Type',
        compute='_compute_job_type_id', store=True, readonly=False, precompute=True,
        help='Which job card (trade) this defect is sent to. Defaults to the category job type.')
    job_card_id = fields.Many2one(
        'fleet.vehicle.log.services', string='Job Card', copy=False, index=True,
        ondelete='set null', readonly=True)
    repair_state = fields.Selection([
        ('pending', 'Awaiting Job Card'),
        ('in_repair', 'In Repair'),
        ('fixed', 'Fixed'),
        ('cancelled', 'Job Cancelled'),
    ], string='Repair Status', compute='_compute_repair_state', store=True)
    is_repeat_defect = fields.Boolean(
        string='Repeat Defect', copy=False, readonly=True,
        help='This item was also reported defective on the previous inspection of this vehicle.')

    vehicle_id = fields.Many2one(related='inspection_id.vehicle_id', store=True)
    inspection_date = fields.Date(related='inspection_id.date', store=True, string='Inspection Date')
    inspection_state = fields.Selection(related='inspection_id.state', store=True)
    mechanic_id = fields.Many2one(related='inspection_id.mechanic_id', store=True)
    company_id = fields.Many2one(related='inspection_id.company_id', store=True)

    @api.depends('category_id')
    def _compute_job_type_id(self):
        for line in self:
            line.job_type_id = line.category_id.job_type_id

    @api.depends('position_id', 'inspection_id.vehicle_id')
    def _compute_lot_id(self):
        Part = self.env['fleet.vehicle.installed.part'].sudo()
        for line in self:
            vehicle = line.inspection_id.vehicle_id
            if not line.position_id or not vehicle:
                line.lot_id = line.lot_id
                continue
            part = Part.search([
                ('vehicle_id', '=', vehicle._origin.id or vehicle.id),
                ('position_id', '=', line.position_id.id),
                ('status', '=', 'installed'),
            ], limit=1)
            line.lot_id = part.lot_id

    @api.depends('tread_depth', 'lot_id')
    def _compute_below_min_tread(self):
        for line in self:
            minimum = line.lot_id.product_id.fleet_min_tread_depth
            line.below_min_tread = bool(line.tread_depth and minimum and line.tread_depth < minimum)

    @api.depends('result', 'job_card_id', 'job_card_id.state')
    def _compute_repair_state(self):
        for line in self:
            if line.result != 'defective':
                line.repair_state = False
            elif not line.job_card_id:
                line.repair_state = 'pending'
            elif line.job_card_id.state == 'completed':
                line.repair_state = 'fixed'
            elif line.job_card_id.state == 'cancel':
                line.repair_state = 'cancelled'
            else:
                line.repair_state = 'in_repair'

    @api.onchange('item_id')
    def _onchange_item_id(self):
        if self.item_id:
            self.category_id = self.item_id.category_id
            self.severity = self.item_id.default_severity

    @api.onchange('result')
    def _onchange_result(self):
        if self.result != 'defective':
            self.severity = 'low'
        elif self.item_id:
            self.severity = self.item_id.default_severity

    @api.onchange('tread_depth')
    def _onchange_tread_depth(self):
        minimum = self.lot_id.product_id.fleet_min_tread_depth
        if self.tread_depth and minimum and self.tread_depth < minimum:
            self.result = 'defective'
            self.severity = 'high'
            if not self.comment:
                self.comment = _('Tread %(depth)s mm below minimum %(min)s mm',
                                 depth=self.tread_depth, min=minimum)

    def _flag_worn_tyres(self):
        """Server-side counterpart of the tread onchange (imports, mobile entry)."""
        for line in self.filtered(lambda l: l.below_min_tread and l.result != 'defective'):
            line.write({
                'result': 'defective',
                'severity': 'high',
                'comment': line.comment or _('Tread %(depth)s mm below minimum %(min)s mm',
                                             depth=line.tread_depth,
                                             min=line.lot_id.product_id.fleet_min_tread_depth),
            })

    def action_open_inspection(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fleet.inspection',
            'view_mode': 'form',
            'res_id': self.inspection_id.id,
        }
