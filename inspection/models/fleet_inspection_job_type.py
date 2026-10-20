# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FleetInspectionJobType(models.Model):
    """Trade / workshop section a defect belongs to (Mechanical, Electrical, ...).

    Defects of an inspection are split per job type so that one inspection can
    produce several job cards, e.g. one for the mechanics and one for the
    electricians.
    """
    _name = 'fleet.inspection.job.type'
    _description = 'Inspection Job Type'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(help='Short code shown on job cards, e.g. MECH, ELEC.')
    sequence = fields.Integer(default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    service_type_id = fields.Many2one(
        'fleet.service.type', string='Job Card Service Type',
        help='Service type used on job cards created for this job type. '
             'Falls back to a generic "Repair" service type when empty.')
    responsible_id = fields.Many2one(
        'hr.employee', string='Default Technician',
        help='Technician assigned by default on job cards of this type '
             '(when the Fleet Workshop module is installed).')
    workshop_id = fields.Many2one(
        'fleet.workshop', string='Default Workshop',
        help='Workshop / bay that receives job cards of this type.')
    category_ids = fields.One2many('fleet.inspection.category', 'job_type_id', string='Categories')
    category_count = fields.Integer(compute='_compute_category_count')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'The job type code must be unique per company!'),
    ]

    @api.depends('category_ids')
    def _compute_category_count(self):
        for rec in self:
            rec.category_count = len(rec.category_ids)
