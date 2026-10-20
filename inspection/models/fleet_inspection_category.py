# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FleetInspectionCategory(models.Model):
    _name = 'fleet.inspection.category'
    _description = 'Fleet Inspection Category'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    vehicle_type_ids = fields.Many2many(
        'fleet.vehicle.model.category', string='Applicable Vehicle Types',
        help='Leave empty to apply this category to every vehicle type.')
    job_type_id = fields.Many2one(
        'fleet.inspection.job.type', string='Job Type',
        default=lambda self: self.env.ref('inspection.job_type_mechanical', raise_if_not_found=False),
        help='Defects found in this category are sent to a job card of this type '
             '(e.g. Electrical categories go to the electricians).')
    item_ids = fields.One2many('fleet.inspection.item', 'category_id', string='Checklist Items')
    item_count = fields.Integer(compute='_compute_item_count')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    def _compute_item_count(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)

    @api.model
    def _assign_default_job_types(self):
        """Give every category without a job type a sensible default based on its
        name, and propagate it to existing checklist lines. Idempotent: only
        touches records that have no job type yet."""
        mechanical = self.env.ref('inspection.job_type_mechanical', raise_if_not_found=False)
        electrical = self.env.ref('inspection.job_type_electrical', raise_if_not_found=False)
        body = self.env.ref('inspection.job_type_body', raise_if_not_found=False)
        tyres = self.env.ref('inspection.job_type_tyres', raise_if_not_found=False)
        keywords = [
            (electrical, ('ELECTRIC', 'LIGHT', 'BATTER', 'WIRING')),
            (tyres, ('TYRE', 'TIRE')),
            (body, ('CAB', 'PANEL', 'BODY', 'FRAME')),
        ]
        categories = self.with_context(active_test=False).search([('job_type_id', '=', False)])
        for category in categories:
            name = (category.name or '').upper()
            job_type = mechanical
            for candidate, words in keywords:
                if candidate and any(word in name for word in words):
                    job_type = candidate
                    break
            if job_type:
                category.job_type_id = job_type
        lines = self.env['fleet.inspection.line'].search([
            ('job_type_id', '=', False), ('category_id.job_type_id', '!=', False)])
        for category, cat_lines in lines.grouped('category_id').items():
            cat_lines.write({'job_type_id': category.job_type_id.id})
