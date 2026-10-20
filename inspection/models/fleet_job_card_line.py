# -*- coding: utf-8 -*-
from odoo import fields, models


class FleetJobCardLine(models.Model):
    _name = 'fleet.job.card.line'
    _description = 'Fleet Job Card Repair Task / Defect Line'
    _order = 'sequence, id'

    job_id = fields.Many2one('fleet.vehicle.log.services', string='Job Card',
                             required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one('fleet.inspection.category', string='Category')
    problem = fields.Char(string='Problem', required=True)
    inspection_line_id = fields.Many2one('fleet.inspection.line', string='Source Inspection Item',
                                         help='Defect line this task originated from, if any.')
    position_id = fields.Many2one(related='inspection_line_id.position_id', string='Position')
    lot_id = fields.Many2one(related='inspection_line_id.lot_id', string='Serial No.')
    severity = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], default='medium')
    description = fields.Text(string='Description')
    recommendation = fields.Text(string='Recommendation')
    action_taken = fields.Text(string='Action Taken')
    estimated_labour = fields.Float(string='Estimated Labour (hrs)')
    estimated_cost = fields.Float(string='Estimated Cost')
    completed = fields.Boolean(string='Completed')
    completed_by = fields.Many2one('hr.employee', string='Done By')
    vehicle_id = fields.Many2one(related='job_id.vehicle_id', store=True)
    job_state = fields.Selection(related='job_id.state')
