# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Kinds of serialised parts followed per vehicle / position.
FLEET_PART_TYPES = [
    ('tyre', 'Tyre'),
    ('battery', 'Battery'),
    ('other', 'Other Serialised Part'),
]


class FleetVehiclePartPosition(models.Model):
    """Where a serialised part sits on a vehicle, e.g. a wheel position (FL, D1LI)."""
    _name = 'fleet.vehicle.part.position'
    _description = 'Vehicle Part Position'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help='Short code used on the inspection sheet, e.g. FL, D1LI.')
    sequence = fields.Integer(default=10)
    part_type = fields.Selection(FLEET_PART_TYPES, default='tyre', required=True)
    axle = fields.Integer(string='Axle No.')
    side = fields.Selection([
        ('left', 'Left'),
        ('right', 'Right'),
        ('center', 'Centre'),
    ])
    vehicle_type_ids = fields.Many2many(
        'fleet.vehicle.model.category', string='Applicable Vehicle Types',
        help='Leave empty to apply this position to every vehicle type.')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The position code must be unique!'),
    ]

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '[%s] %s' % (rec.code, rec.name) if rec.code else rec.name
