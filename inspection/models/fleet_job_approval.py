# -*- coding: utf-8 -*-
from odoo import fields, models


class FleetJobApproval(models.Model):
    _name = 'fleet.job.approval'
    _description = 'Fleet Job / Material / Purchase Approval Log'
    _order = 'date desc, id desc'

    job_id = fields.Many2one('fleet.vehicle.log.services', string='Job Card', ondelete='cascade', index=True)
    material_request_id = fields.Many2one('fleet.job.material.request', string='Material Request',
                                          ondelete='cascade', index=True)
    approval_type = fields.Selection([
        ('job_card', 'Job Card'),
        ('material_request', 'Material Request'),
        ('purchase', 'Purchase'),
        ('quality', 'Quality Check'),
    ], required=True)
    stage = fields.Char(string='Stage', help='e.g. Workshop Supervisor, Fleet Manager, Store Keeper')
    approver_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    date = fields.Datetime(default=fields.Datetime.now)
    state = fields.Selection([
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], required=True)
    comment = fields.Char()

    def _log(self, record, approval_type, stage, state='approved', comment=False):
        """Create a log line for a job card or a material request."""
        vals = {
            'approval_type': approval_type,
            'stage': stage,
            'state': state,
            'comment': comment,
        }
        if record._name == 'fleet.job.material.request':
            vals['material_request_id'] = record.id
        else:
            vals['job_id'] = record.id
        return self.sudo().create(vals)
