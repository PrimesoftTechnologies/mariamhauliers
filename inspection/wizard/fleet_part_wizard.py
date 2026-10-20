# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.fleet_vehicle_installed_part import REMOVAL_DESTINATIONS, REMOVAL_REASONS


class FleetPartFitmentWizard(models.TransientModel):
    """Fit the serialised parts issued to a job card (tyres, batteries) on the vehicle.

    The part currently at the chosen position is removed automatically; a serial
    already fitted elsewhere on the vehicle is moved (rotation)."""
    _name = 'fleet.part.fitment.wizard'
    _description = 'Record Part Fitment'

    job_id = fields.Many2one('fleet.vehicle.log.services', string='Job Card', required=True)
    vehicle_id = fields.Many2one(related='job_id.vehicle_id')
    date = fields.Date(default=fields.Date.context_today, required=True)
    mileage = fields.Float(string='Odometer', required=True)
    installed_by = fields.Many2one('hr.employee', string='Fitted By')
    line_ids = fields.One2many('fleet.part.fitment.wizard.line', 'wizard_id', string='Parts')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        job = self.env['fleet.vehicle.log.services'].browse(res.get('job_id') or self.env.context.get('active_id'))
        if not job:
            return res
        res['job_id'] = job.id
        res['mileage'] = job.current_mileage or job.vehicle_id.odometer
        res['installed_by'] = job.technician_id.id
        # Suggest the positions reported defective on the inspection, in order
        free_positions = [jl.position_id for jl in job.job_line_ids if jl.position_id]
        lines = []
        for mr_line in job._pending_fitment_lines():
            for lot in mr_line.pending_fit_lot_ids:
                position = next((p for p in free_positions if p.part_type == mr_line.fleet_part_type), False)
                if position:
                    free_positions.remove(position)
                lines.append(fields.Command.create({
                    'mr_line_id': mr_line.id,
                    'product_id': mr_line.product_id.id,
                    'lot_id': lot.id,
                    'position_id': position.id if position else False,
                    'cost': mr_line.unit_cost,
                    'tread_depth': mr_line.product_id.fleet_new_tread_depth,
                }))
        res['line_ids'] = lines
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Nothing to fit.'))
        Part = self.env['fleet.vehicle.installed.part']
        vehicle = self.vehicle_id
        for line in self.line_ids:
            if line.product_id.tracking == 'serial' and not line.lot_id:
                raise UserError(_('Select the serial number of %s.', line.product_id.display_name))
            if line.product_id.fleet_part_type and not line.position_id:
                raise UserError(_('Select the position of %s.', line.lot_id.name or line.product_id.display_name))
        if len(self.line_ids.position_id) != len(self.line_ids.filtered('position_id')):
            raise UserError(_('Two parts cannot be fitted on the same position.'))
        # 1. removals first, so that rotations / swaps work
        for line in self.line_ids:
            moved = Part.search([('lot_id', '=', line.lot_id.id), ('status', '=', 'installed')]) \
                if line.lot_id else Part
            if moved and moved.vehicle_id != vehicle:
                raise UserError(_('%(lot)s is fitted on %(vehicle)s: remove it there first.',
                                  lot=line.lot_id.name, vehicle=moved.vehicle_id.display_name))
            moved._action_remove(date=self.date, mileage=self.mileage, reason='rotation', destination='refit',
                                 removed_by=self.installed_by, job=self.job_id)
            replaced = line.replaced_part_id.filtered(lambda p: p.status == 'installed')
            if replaced:
                replaced._action_remove(date=self.date, mileage=self.mileage, reason=line.removal_reason,
                                        destination=line.removal_destination, removed_by=self.installed_by,
                                        job=self.job_id, tread=line.removed_tread_depth)
        # 2. new fitments
        created = Part
        for line in self.line_ids:
            created |= Part.create({
                'vehicle_id': vehicle.id,
                'job_id': self.job_id.id,
                'material_request_line_id': line.mr_line_id.id,
                'product_id': line.product_id.id,
                'lot_id': line.lot_id.id,
                'position_id': line.position_id.id,
                'install_date': self.date,
                'installed_by': self.installed_by.id,
                'mileage_at_install': self.mileage,
                'tread_depth_at_install': line.tread_depth,
                'cost': line.cost,
            })
        self.job_id.message_post(body=Markup('<p>%s</p><ul>%s</ul>') % (
            _('Parts fitted:'),
            Markup('').join(Markup('<li>%s - %s</li>') % (p.position_id.display_name or '-', p.part_number or p.name)
                            for p in created)))
        return {'type': 'ir.actions.act_window_close'}


class FleetPartFitmentWizardLine(models.TransientModel):
    _name = 'fleet.part.fitment.wizard.line'
    _description = 'Record Part Fitment - Line'

    wizard_id = fields.Many2one('fleet.part.fitment.wizard', required=True, ondelete='cascade')
    mr_line_id = fields.Many2one('fleet.job.material.request.line', string='Material Line')
    product_id = fields.Many2one('product.product', string='Part', required=True)
    lot_id = fields.Many2one('stock.lot', string='Serial No.', domain="[('product_id', '=', product_id)]")
    position_id = fields.Many2one('fleet.vehicle.part.position', string='Position')
    tread_depth = fields.Float(string='Tread (mm)', digits=(16, 1))
    cost = fields.Float(string='Cost')
    replaced_part_id = fields.Many2one('fleet.vehicle.installed.part', string='Replaces',
                                       compute='_compute_replaced_part_id')
    removal_reason = fields.Selection(REMOVAL_REASONS, default='worn_out', string='Removal Reason')
    removal_destination = fields.Selection(REMOVAL_DESTINATIONS, default='scrap', string='Removed Part To')
    removed_tread_depth = fields.Float(string='Removed Tread (mm)', digits=(16, 1))

    @api.depends('position_id', 'wizard_id.vehicle_id')
    def _compute_replaced_part_id(self):
        Part = self.env['fleet.vehicle.installed.part']
        for line in self:
            vehicle = line.wizard_id.vehicle_id
            line.replaced_part_id = Part.search([
                ('vehicle_id', '=', vehicle.id), ('position_id', '=', line.position_id.id),
                ('status', '=', 'installed'),
            ], limit=1) if vehicle and line.position_id else Part


class FleetPartRemovalWizard(models.TransientModel):
    _name = 'fleet.part.removal.wizard'
    _description = 'Remove Fitted Part'

    part_ids = fields.Many2many('fleet.vehicle.installed.part', string='Parts', required=True,
                                domain=[('status', '=', 'installed')])
    vehicle_id = fields.Many2one('fleet.vehicle', compute='_compute_vehicle_id')
    date = fields.Date(default=fields.Date.context_today, required=True)
    mileage = fields.Float(string='Odometer', required=True)
    reason = fields.Selection(REMOVAL_REASONS, required=True, default='worn_out')
    destination = fields.Selection(REMOVAL_DESTINATIONS, required=True, default='scrap', string='Send To')
    removed_by = fields.Many2one('hr.employee', string='Removed By',
                                 default=lambda self: self.env.user.employee_id)
    job_id = fields.Many2one('fleet.vehicle.log.services', string='Job Card',
                             domain="[('vehicle_id', '=', vehicle_id), ('state', 'not in', ('completed', 'cancel'))]")
    tread_depth = fields.Float(string='Tread at Removal (mm)', digits=(16, 1))
    notes = fields.Char()

    @api.depends('part_ids')
    def _compute_vehicle_id(self):
        for wizard in self:
            wizard.vehicle_id = wizard.part_ids.vehicle_id[:1]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        part_ids = res.get('part_ids') or self.env.context.get('active_ids') or []
        if part_ids and isinstance(part_ids[0], (list, tuple)):
            part_ids = part_ids[0][2] if len(part_ids[0]) > 2 else []
        parts = self.env['fleet.vehicle.installed.part'].browse(part_ids).exists()
        if parts:
            res['part_ids'] = [fields.Command.set(parts.ids)]
            res['mileage'] = parts.vehicle_id[:1].odometer
        return res

    def action_confirm(self):
        self.ensure_one()
        if len(self.part_ids.vehicle_id) > 1:
            raise UserError(_('Remove parts of one vehicle at a time.'))
        self.part_ids._action_remove(date=self.date, mileage=self.mileage, reason=self.reason,
                                     destination=self.destination, removed_by=self.removed_by,
                                     job=self.job_id, tread=self.tread_depth, notes=self.notes)
        return {'type': 'ir.actions.act_window_close'}
