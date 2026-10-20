# -*- coding: utf-8 -*-
from odoo import fields, models


class FleetInspectionItem(models.Model):
    _name = 'fleet.inspection.item'
    _description = 'Fleet Inspection Checklist Item'
    _order = 'category_id, sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one('fleet.inspection.category', required=True,
                                   ondelete='cascade', string='Category')
    default_severity = fields.Selection(
        [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        string='Default Severity', default='low',
        help='Severity suggested when this item is marked Defective.')
    vehicle_type_ids = fields.Many2many(
        'fleet.vehicle.model.category', string='Applicable Vehicle Types',
        help='Leave empty to apply this item to every vehicle type.')
    position_id = fields.Many2one(
        'fleet.vehicle.part.position', string='Part Position',
        help='Wheel / part position checked by this item. The serial number fitted at this '
             'position is shown on the inspection, with tread depth and pressure for tyres.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', related='category_id.company_id', store=True)
