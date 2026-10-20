# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .fleet_part_position import FLEET_PART_TYPES

FLEET_TRANSFER_TYPES = [
    ('issue', 'Issue to Job Card'),
    ('return', 'Return from Job Card'),
    ('part_return', 'Removed Part Return'),
]


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    workshop_material_request_id = fields.Many2one('fleet.job.material.request', string='Material Request',
                                                   index=True)
    fleet_transfer_type = fields.Selection(FLEET_TRANSFER_TYPES, string='Workshop Transfer', copy=True)
    fleet_job_id = fields.Many2one(related='workshop_material_request_id.job_id', string='Job Card')
    fleet_vehicle_id = fields.Many2one(related='workshop_material_request_id.vehicle_id', string='Vehicle')

    def _action_done(self):
        res = super()._action_done()
        self._fleet_after_done()
        return res

    def _fleet_after_done(self):
        done = self.filtered(lambda p: p.state == 'done')
        if not done:
            return
        # Serial numbers status (tyres, batteries...)
        for picking in done.filtered('fleet_transfer_type'):
            lots = picking.move_line_ids.lot_id
            if picking.fleet_transfer_type == 'issue':
                lots.filtered(lambda l: l.fleet_status != 'installed').sudo().write({'fleet_status': 'issued'})
            elif picking.fleet_transfer_type == 'return':
                lots.sudo().write({'fleet_status': 'in_stock'})
        # Issue transfers validated: update the requests (Issued / partially issued)
        requests = done.workshop_material_request_id
        if requests:
            requests.sudo()._update_availability()
        # Stock arrived (receipt, return, internal move): serve the waiting requests
        arrived = done.filtered(
            lambda p: p.location_dest_id.usage == 'internal' and p.fleet_transfer_type != 'issue')
        products = arrived.move_ids.product_id
        if products:
            waiting = self.env['fleet.job.material.request'].sudo().search([
                ('state', 'in', ('approved', 'waiting_stock')),
                ('line_ids.product_id', 'in', products.ids),
            ])
            waiting._on_stock_arrived()

    @api.model
    def _fleet_create_done_transfer(self, items, location, location_dest, picking_type, origin,
                                    transfer_type, request=False):
        """Create and validate a transfer in one go (returns of unused parts,
        removed tyres sent back to stock...).

        :param items: list of dicts {product, qty, uom, lots (stock.lot), mr_line}
        """
        Picking = self.sudo()
        company = picking_type.company_id or (request and request.company_id) or self.env.company
        picking = Picking.create({
            'picking_type_id': picking_type.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'origin': origin,
            'fleet_transfer_type': transfer_type,
            'workshop_material_request_id': request.id if request else False,
            'company_id': company.id,
        })
        Move = self.env['stock.move'].sudo()
        moves_items = []
        for item in items:
            product = item['product']
            uom = item.get('uom') or product.uom_id
            move = Move.create({
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': item['qty'],
                'product_uom': uom.id,
                'location_id': location.id,
                'location_dest_id': location_dest.id,
                'picking_id': picking.id,
                'picking_type_id': picking_type.id,
                'company_id': company.id,
                'material_request_line_id': item.get('mr_line') and item['mr_line'].id,
                'origin': origin,
            })
            moves_items.append((move, item))
        picking.action_confirm()
        MoveLine = self.env['stock.move.line'].sudo()
        for move, item in moves_items:
            move.move_line_ids.unlink()
            lots = item.get('lots') or self.env['stock.lot']
            base = {
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'location_id': location.id,
                'location_dest_id': location_dest.id,
                'company_id': company.id,
            }
            if lots:
                for lot in lots:
                    MoveLine.create(dict(base, lot_id=lot.id, quantity=1.0))
            else:
                MoveLine.create(dict(base, quantity=item['qty']))
        picking.move_ids.write({'picked': True})
        picking._action_done()
        return picking


class StockMove(models.Model):
    _inherit = 'stock.move'

    material_request_line_id = fields.Many2one('fleet.job.material.request.line', string='Material Request Line',
                                               index=True, copy=False)


class StockLot(models.Model):
    _inherit = 'stock.lot'

    fleet_part_type = fields.Selection(FLEET_PART_TYPES, related='product_id.fleet_part_type', store=True,
                                       string='Fleet Part Type')
    fleet_status = fields.Selection([
        ('in_stock', 'In Stock'),
        ('issued', 'Issued / To Fit'),
        ('installed', 'Fitted on Vehicle'),
        ('removed', 'Removed'),
        ('retread', 'At Retreading'),
        ('scrapped', 'Scrapped'),
    ], string='Fleet Status', default='in_stock', tracking=True, copy=False)
    installed_part_ids = fields.One2many('fleet.vehicle.installed.part', 'lot_id', string='Fitment History')
    fleet_vehicle_id = fields.Many2one('fleet.vehicle', string='Fitted on Vehicle',
                                       compute='_compute_fleet_current', store=True, index=True)
    fleet_position_id = fields.Many2one('fleet.vehicle.part.position', string='Position',
                                        compute='_compute_fleet_current', store=True)
    fleet_install_date = fields.Date(string='Fitted On', compute='_compute_fleet_current', store=True)
    fleet_install_count = fields.Integer(string='Fitments', compute='_compute_fleet_current', store=True)
    fleet_km_completed = fields.Float(string='Km (previous fitments)', compute='_compute_fleet_current', store=True)
    fleet_km_current = fields.Float(string='Km (current fitment)', compute='_compute_fleet_km')
    fleet_km_total = fields.Float(string='Total Km', compute='_compute_fleet_km')
    fleet_wear_pct = fields.Float(string='Life Used (%)', compute='_compute_fleet_km',
                                  help='Total km compared to the expected life set on the product.')
    fleet_cost = fields.Float(string='Part Cost', compute='_compute_fleet_km')
    fleet_cost_per_km = fields.Float(string='Cost / Km', compute='_compute_fleet_km', digits=(16, 4))
    fleet_retread_count = fields.Integer(string='Retreads', copy=False)
    fleet_inspection_line_ids = fields.One2many('fleet.inspection.line', 'lot_id', string='Inspection Readings')
    fleet_last_tread_depth = fields.Float(string='Last Tread (mm)', compute='_compute_fleet_last_reading')
    fleet_last_reading_date = fields.Date(string='Last Reading', compute='_compute_fleet_last_reading')

    @api.depends('installed_part_ids.status', 'installed_part_ids.vehicle_id', 'installed_part_ids.position_id',
                 'installed_part_ids.install_date', 'installed_part_ids.mileage_covered')
    def _compute_fleet_current(self):
        for lot in self:
            parts = lot.installed_part_ids
            current = parts.filtered(lambda p: p.status == 'installed')[:1]
            lot.fleet_vehicle_id = current.vehicle_id
            lot.fleet_position_id = current.position_id
            lot.fleet_install_date = current.install_date
            lot.fleet_install_count = len(parts)
            lot.fleet_km_completed = sum(parts.filtered(lambda p: p.status == 'removed').mapped('mileage_covered'))

    def _compute_fleet_km(self):
        for lot in self:
            current = lot.installed_part_ids.filtered(lambda p: p.status == 'installed')[:1]
            lot.fleet_km_current = current.current_km if current else 0.0
            lot.fleet_km_total = lot.fleet_km_completed + lot.fleet_km_current
            expected = lot.product_id.fleet_expected_life_km
            lot.fleet_wear_pct = (100.0 * lot.fleet_km_total / expected) if expected else 0.0
            fitted_cost = lot.installed_part_ids.sorted('install_date')[:1].cost
            lot.fleet_cost = fitted_cost or lot.product_id.standard_price
            lot.fleet_cost_per_km = (lot.fleet_cost / lot.fleet_km_total) if lot.fleet_km_total else 0.0

    def _compute_fleet_last_reading(self):
        for lot in self:
            readings = lot.fleet_inspection_line_ids.filtered(
                lambda l: l.tread_depth and l.inspection_state in ('completed', 'approved'))
            last = readings.sorted(lambda l: (l.inspection_date, l.id), reverse=True)[:1]
            lot.fleet_last_tread_depth = last.tread_depth
            lot.fleet_last_reading_date = last.inspection_date

    def _fleet_needs_replacement(self, wear_warning_pct=90.0):
        """True when the part reached its wear warning (km) or its minimum tread."""
        self.ensure_one()
        minimum = self.product_id.fleet_min_tread_depth
        if self.fleet_last_tread_depth and minimum and self.fleet_last_tread_depth <= minimum:
            return True
        return bool(self.product_id.fleet_expected_life_km and self.fleet_wear_pct >= wear_warning_pct)

    def _fleet_return_to_stock(self, workshop=False, origin=False):
        """Bring removed / retreaded serials back from the consumption location to the
        workshop used-parts store, so they can be issued again as spares."""
        Picking = self.env['stock.picking']
        workshop = workshop or self.env['fleet.workshop']
        for lot in self.sudo():
            quant = lot.quant_ids.filtered(lambda q: q.quantity > 0 and q.location_id.usage != 'internal')[:1]
            if not quant:
                continue  # fitted without passing through stock (initial fitment): status only
            warehouse, source, dest, picking_type = workshop._get_stock_settings(
                company=lot.company_id or self.env.company, raise_if_missing=False)
            target = workshop.used_location_id or source
            if not target or not picking_type:
                continue
            Picking._fleet_create_done_transfer(
                [{'product': lot.product_id, 'qty': 1.0, 'lots': lot}],
                quant.location_id, target, picking_type,
                origin=origin or _('Return of %s', lot.name), transfer_type='part_return')
            lot.fleet_status = 'in_stock'

    def action_fleet_back_from_retread(self):
        for lot in self:
            if lot.fleet_status != 'retread':
                raise UserError(_('%s is not at retreading.', lot.name))
        self._fleet_return_to_stock(origin=_('Back from retreading'))
        self.sudo().write({'fleet_status': 'in_stock'})
        return True

    def action_fleet_scrap(self):
        self.filtered(lambda l: l.fleet_status != 'installed').sudo().write({'fleet_status': 'scrapped'})
        return True

    def action_view_fleet_history(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fitment History - %s', self.name),
            'res_model': 'fleet.vehicle.installed.part',
            'view_mode': 'list,form',
            'domain': [('lot_id', '=', self.id)],
            'context': {'default_lot_id': self.id, 'default_product_id': self.product_id.id},
        }
