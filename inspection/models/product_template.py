# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .fleet_part_position import FLEET_PART_TYPES


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fleet_part_type = fields.Selection(
        FLEET_PART_TYPES, string='Fleet Part Type',
        help='Serial numbers of this product are followed per vehicle and position '
             '(fitment, removal, km covered, cost per km).')
    fleet_expected_life_km = fields.Float(
        string='Expected Life (km)',
        help='Used to warn when a fitted part approaches the end of its life.')
    fleet_new_tread_depth = fields.Float(string='New Tread Depth (mm)')
    fleet_min_tread_depth = fields.Float(
        string='Min. Tread Depth (mm)',
        help='A tyre measured below this depth during an inspection is flagged defective.')

    @api.onchange('fleet_part_type')
    def _onchange_fleet_part_type(self):
        if self.fleet_part_type:
            self.is_storable = True
            self.tracking = 'serial'
            if self.fleet_part_type == 'tyre' and not self.fleet_min_tread_depth:
                self.fleet_min_tread_depth = 3.0
