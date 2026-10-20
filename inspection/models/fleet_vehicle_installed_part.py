# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .fleet_part_position import FLEET_PART_TYPES

REMOVAL_REASONS = [
    ('worn_out', 'Worn Out'),
    ('damaged', 'Damaged'),
    ('puncture', 'Puncture'),
    ('rotation', 'Rotation'),
    ('retread', 'Sent for Retreading'),
    ('replaced', 'Replaced'),
    ('transfer', 'Transfer to Another Vehicle'),
    ('other', 'Other'),
]

REMOVAL_DESTINATIONS = [
    ('stock', 'Back to Stock (spare)'),
    ('refit', 'Re-fit Elsewhere'),
    ('retread', 'Retreading'),
    ('scrap', 'Scrap'),
]


class FleetVehicleInstalledPart(models.Model):
    """One fitment of a part on a vehicle (tyre, battery, ...), from fitment to removal."""
    _name = 'fleet.vehicle.installed.part'
    _description = 'Vehicle Installed Part History'
    _order = 'install_date desc, id desc'

    vehicle_id = fields.Many2one('fleet.vehicle', string='Vehicle', compute='_compute_vehicle_id',
                                 store=True, readonly=False, index=True)
    job_id = fields.Many2one('fleet.vehicle.log.services', string='Fitted via Job Card', index=True)
    removal_job_id = fields.Many2one('fleet.vehicle.log.services', string='Removed via Job Card', index=True)
    material_request_line_id = fields.Many2one('fleet.job.material.request.line', string='Material Line',
                                               index=True)

    product_id = fields.Many2one('product.product', string='Part')
    lot_id = fields.Many2one('stock.lot', string='Serial No.', index=True,
                             domain="[('product_id', '=', product_id)]")
    part_type = fields.Selection(FLEET_PART_TYPES, compute='_compute_part_type', store=True, readonly=False)
    name = fields.Char(string='Part Name', compute='_compute_name', store=True, readonly=False)
    brand = fields.Char(string='Brand')
    part_number = fields.Char(string='Part / Serial Number', compute='_compute_part_number',
                              store=True, readonly=False)
    size = fields.Char(string='Size')
    position_id = fields.Many2one('fleet.vehicle.part.position', string='Position')
    position = fields.Char(string='Position Details', help='Free text, e.g. engine bay, rear axle.')

    install_date = fields.Date(string='Fitted On', default=fields.Date.context_today, required=True)
    installed_by = fields.Many2one('hr.employee', string='Fitted By')
    mileage_at_install = fields.Float(string='Km at Fitment')
    tread_depth_at_install = fields.Float(string='Tread at Fitment (mm)', digits=(16, 1))

    remove_date = fields.Date(string='Removed On')
    removed_by = fields.Many2one('hr.employee', string='Removed By')
    mileage_at_removal = fields.Float(string='Km at Removal')
    tread_depth_at_removal = fields.Float(string='Tread at Removal (mm)', digits=(16, 1))
    removal_reason = fields.Selection(REMOVAL_REASONS, string='Removal Reason')
    removal_destination = fields.Selection(REMOVAL_DESTINATIONS, string='Sent To')
    removal_notes = fields.Char(string='Removal Notes')

    status = fields.Selection([
        ('installed', 'Fitted'),
        ('removed', 'Removed'),
    ], default='installed', required=True, index=True)

    mileage_covered = fields.Float(string='Km Covered', compute='_compute_mileage_covered', store=True,
                                   aggregator='sum')
    current_km = fields.Float(string='Km Running', compute='_compute_current_km',
                              help='Km covered so far for a part still fitted, km covered for a removed part.')
    cost = fields.Float(string='Part Cost', aggregator='sum')
    cost_per_km = fields.Float(string='Cost / Km', compute='_compute_current_km', digits=(16, 4))
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    def init(self):
        # A serial number can be fitted on one vehicle at a time.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS fleet_vehicle_installed_part_lot_fitted_uniq
                ON fleet_vehicle_installed_part (lot_id)
             WHERE status = 'installed' AND lot_id IS NOT NULL
        """)

    # ------------------------------------------------------------------ computes
    @api.depends('job_id')
    def _compute_vehicle_id(self):
        for rec in self:
            rec.vehicle_id = rec.job_id.vehicle_id or rec.vehicle_id

    @api.depends('product_id')
    def _compute_part_type(self):
        for rec in self:
            rec.part_type = rec.product_id.fleet_part_type or rec.part_type

    @api.depends('product_id')
    def _compute_name(self):
        for rec in self:
            if rec.product_id and not rec.name:
                rec.name = rec.product_id.display_name
            else:
                rec.name = rec.name

    @api.depends('lot_id')
    def _compute_part_number(self):
        for rec in self:
            rec.part_number = rec.lot_id.name or rec.part_number

    @api.depends('mileage_at_install', 'mileage_at_removal', 'status')
    def _compute_mileage_covered(self):
        for rec in self:
            if rec.status == 'removed' and rec.mileage_at_removal:
                rec.mileage_covered = max(rec.mileage_at_removal - rec.mileage_at_install, 0.0)
            else:
                rec.mileage_covered = 0.0

    def _compute_current_km(self):
        for rec in self:
            if rec.status == 'installed':
                rec.current_km = max((rec.vehicle_id.odometer or 0.0) - rec.mileage_at_install, 0.0)
            else:
                rec.current_km = rec.mileage_covered
            rec.cost_per_km = (rec.cost / rec.current_km) if rec.current_km else 0.0

    # ------------------------------------------------------------------ onchange
    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id and not self.mileage_at_install:
            self.mileage_at_install = self.vehicle_id.odometer

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.cost = self.cost or self.product_id.standard_price
            self.tread_depth_at_install = self.tread_depth_at_install or self.product_id.fleet_new_tread_depth

    # ------------------------------------------------------------------ constraints
    @api.constrains('lot_id', 'status')
    def _check_lot_fitted_once(self):
        for rec in self.filtered(lambda r: r.lot_id and r.status == 'installed'):
            other = self.sudo().search([
                ('lot_id', '=', rec.lot_id.id), ('status', '=', 'installed'), ('id', '!=', rec.id)], limit=1)
            if other:
                raise ValidationError(_('Serial number %(lot)s is already fitted on %(vehicle)s (%(pos)s). '
                                        'Remove it first.', lot=rec.lot_id.name,
                                        vehicle=other.vehicle_id.display_name,
                                        pos=other.position_id.display_name or '-'))

    @api.constrains('vehicle_id', 'position_id', 'status')
    def _check_position_free(self):
        for rec in self.filtered(lambda r: r.vehicle_id and r.position_id and r.status == 'installed'):
            other = self.sudo().search([
                ('vehicle_id', '=', rec.vehicle_id.id), ('position_id', '=', rec.position_id.id),
                ('status', '=', 'installed'), ('id', '!=', rec.id)], limit=1)
            if other:
                raise ValidationError(_('Position %(pos)s of %(vehicle)s already has %(part)s fitted. '
                                        'Remove it first.', pos=rec.position_id.display_name,
                                        vehicle=rec.vehicle_id.display_name,
                                        part=other.part_number or other.name))

    @api.constrains('vehicle_id')
    def _check_vehicle(self):
        if any(not rec.vehicle_id for rec in self):
            raise ValidationError(_('A fitted part must be linked to a vehicle.'))

    @api.constrains('mileage_at_install', 'mileage_at_removal', 'status')
    def _check_mileage(self):
        for rec in self:
            if rec.status == 'removed' and rec.mileage_at_removal and rec.mileage_at_removal < rec.mileage_at_install:
                raise ValidationError(_('Km at removal cannot be lower than km at fitment (%s).',
                                        rec.name or rec.part_number))

    # ------------------------------------------------------------------ CRUD
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.lot_id and r.status == 'installed').lot_id.sudo().write(
            {'fleet_status': 'installed'})
        return records

    # ------------------------------------------------------------------ removal
    def _action_remove(self, date=False, mileage=0.0, reason='other', destination='stock',
                       removed_by=False, job=False, tread=0.0, notes=False):
        """Remove the part(s) from the vehicle and route the serial number."""
        lot_status = {'stock': 'in_stock', 'refit': 'removed', 'retread': 'retread', 'scrap': 'scrapped'}
        for rec in self:
            if rec.status != 'installed':
                raise UserError(_('%s is not fitted anymore.', rec.part_number or rec.name))
            rec.write({
                'status': 'removed',
                'remove_date': date or fields.Date.context_today(self),
                'mileage_at_removal': mileage or rec.vehicle_id.odometer,
                'removal_reason': reason,
                'removal_destination': destination,
                'removed_by': removed_by.id if removed_by else False,
                'removal_job_id': job.id if job else False,
                'tread_depth_at_removal': tread,
                'removal_notes': notes,
            })
            lot = rec.lot_id.sudo()
            if not lot:
                continue
            lot.fleet_status = lot_status.get(destination, 'removed')
            if destination == 'retread':
                lot.fleet_retread_count += 1
            if destination == 'stock':
                lot._fleet_return_to_stock(workshop=(job or rec.job_id).workshop_id, origin=_(
                    'Removed from %(vehicle)s (%(pos)s)', vehicle=rec.vehicle_id.display_name,
                    pos=rec.position_id.display_name or '-'))

    def action_remove_part(self):
        """Open the removal wizard."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remove Part'),
            'res_model': 'fleet.part.removal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_part_ids': self.ids},
        }
