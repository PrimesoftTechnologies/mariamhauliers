# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetWorkshop(models.Model):
    _name = 'fleet.workshop'
    _description = 'Fleet Workshop / Bay'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Source Warehouse',
        help='Warehouse spare parts are issued from, and purchased parts are received in.')
    source_location_id = fields.Many2one(
        'stock.location', string='Issue From',
        domain="[('usage', '=', 'internal')]",
        help='Stock location parts are taken from. Defaults to the warehouse stock location.')
    location_id = fields.Many2one(
        'stock.location', string='Consumption Location',
        domain="[('usage', 'in', ('internal', 'transit', 'inventory'))]",
        default=lambda self: self.env.ref('inspection.stock_location_fleet_consumption', raise_if_not_found=False),
        help='Where issued parts go. Use the virtual "Fleet Maintenance Consumption" location to '
             'take parts out of stock when they are issued, or an internal location to keep them '
             'in a workshop bay store.')
    used_location_id = fields.Many2one(
        'stock.location', string='Used Parts Store',
        domain="[('usage', '=', 'internal')]",
        help='Internal location receiving removed parts kept as spares and tyres back from '
             'retreading. Use a location outside the main stock so used parts are not '
             'reserved for new requests. Defaults to the issue location.')
    default_picking_type_id = fields.Many2one(
        'stock.picking.type', string='Issue Operation Type',
        help='Operation type of the issue transfers. Defaults to the warehouse internal transfers.')
    default_vendor_id = fields.Many2one(
        'res.partner', string='Default Vendor',
        help='Vendor used for shortages of products that have no vendor on the product form.')
    manager_id = fields.Many2one('hr.employee', string='Workshop Supervisor')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        if self.warehouse_id:
            self.source_location_id = self.warehouse_id.lot_stock_id
            self.default_picking_type_id = self.warehouse_id.int_type_id

    @api.model
    def _get_default_workshop(self, company=None):
        company = company or self.env.company
        return self.search([('company_id', 'in', (company.id, False))], limit=1)

    def _get_stock_settings(self, company=None, raise_if_missing=True):
        """Return (warehouse, source location, destination location, picking type)
        used to issue parts. Works without any workshop configured (company
        warehouse + consumption location)."""
        self = self[:1]
        company = self.company_id or company or self.env.company
        warehouse = self.warehouse_id or self.env['stock.warehouse'].sudo().search(
            [('company_id', '=', company.id)], limit=1)
        dest = self.location_id or self.env.ref('inspection.stock_location_fleet_consumption',
                                                raise_if_not_found=False)
        if not warehouse or not dest:
            if raise_if_missing:
                raise UserError(_('No warehouse / consumption location found for company %s. '
                                  'Configure a warehouse and the workshop first.', company.display_name))
            return (warehouse, self.env['stock.location'], dest or self.env['stock.location'],
                    self.env['stock.picking.type'])
        source = self.source_location_id or warehouse.lot_stock_id
        picking_type = self.default_picking_type_id or warehouse.int_type_id
        return warehouse, source, dest, picking_type
