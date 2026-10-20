# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError


class FleetWorkshopReportWizard(models.TransientModel):
    _name = 'fleet.workshop.report.wizard'
    _description = 'Fleet Workshop Summary Report'

    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self) - timedelta(days=29))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    vehicle_ids = fields.Many2many('fleet.vehicle', string='Vehicles', help='Leave empty to include every vehicle.')
    workshop_ids = fields.Many2many('fleet.workshop', string='Workshops', help='Leave empty for every workshop.')
    job_type_ids = fields.Many2many('fleet.inspection.job.type', string='Job Types',
                                    help='Leave empty for every job type.')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    def _get_domain(self):
        """Job cards completed in the period."""
        self.ensure_one()
        domain = [
            ('state', '=', 'completed'),
            ('completion_date', '>=', datetime.combine(self.date_from, time.min)),
            ('completion_date', '<=', datetime.combine(self.date_to, time.max)),
            ('company_id', '=', self.company_id.id),
        ]
        if self.vehicle_ids:
            domain.append(('vehicle_id', 'in', self.vehicle_ids.ids))
        if self.workshop_ids:
            domain.append(('workshop_id', 'in', self.workshop_ids.ids))
        if self.job_type_ids:
            domain.append(('inspection_job_type_id', 'in', self.job_type_ids.ids))
        return domain

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('The start date must be before the end date.'))
        return self.env.ref('inspection.action_report_workshop_summary').report_action(self)

    def action_view_list(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Completed Job Cards'),
            'res_model': 'fleet.vehicle.log.services',
            'view_mode': 'list,form,pivot,graph',
            'domain': self._get_domain(),
        }
