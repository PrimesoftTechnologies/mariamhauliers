# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FleetJobLabourLine(models.Model):
    _name = 'fleet.job.labour.line'
    _description = 'Fleet Job Card Labour Line'
    _order = 'date desc, id desc'

    job_id = fields.Many2one('fleet.vehicle.log.services', string='Job Card',
                             required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Technician', required=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    hours = fields.Float(string='Hours', required=True, default=1.0)
    description = fields.Char(string='Work Performed')
    hourly_rate = fields.Float(string='Hourly Rate')
    amount = fields.Float(string='Amount', compute='_compute_amount', store=True)
    vehicle_id = fields.Many2one(related='job_id.vehicle_id', store=True)
    job_type_id = fields.Many2one(related='job_id.inspection_job_type_id', store=True)
    workshop_id = fields.Many2one(related='job_id.workshop_id', store=True)
    company_id = fields.Many2one(related='job_id.company_id', store=True)

    @api.depends('hours', 'hourly_rate')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.hours * rec.hourly_rate

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        # hourly_cost is restricted to HR officers: read it as superuser.
        employee = self.employee_id.sudo()
        if employee and 'hourly_cost' in employee._fields and employee.hourly_cost:
            self.hourly_rate = employee.hourly_cost
