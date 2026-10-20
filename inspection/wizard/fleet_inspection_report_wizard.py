# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError


class FleetInspectionReportWizard(models.TransientModel):
    _name = 'fleet.inspection.report.wizard'
    _description = 'Fleet Inspection Summary Report'

    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self) - timedelta(days=29))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    vehicle_ids = fields.Many2many('fleet.vehicle', string='Vehicles',
                                   help='Leave empty to include every vehicle.')
    mechanic_ids = fields.Many2many('hr.employee', string='Mechanics',
                                    help='Leave empty to include every mechanic.')
    inspection_type = fields.Selection(
        lambda self: self.env['fleet.inspection']._fields['inspection_type'].selection,
        string='Inspection Type', help='Leave empty to include every type.')
    include_unapproved = fields.Boolean(
        string='Include not yet approved', default=True,
        help='Also include draft, in-progress and completed inspections.')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    def _get_domain(self):
        self.ensure_one()
        domain = [
            ('date', '>=', self.date_from), ('date', '<=', self.date_to),
            ('state', '!=', 'cancel'), ('company_id', '=', self.company_id.id),
        ]
        if not self.include_unapproved:
            domain.append(('state', '=', 'approved'))
        if self.vehicle_ids:
            domain.append(('vehicle_id', 'in', self.vehicle_ids.ids))
        if self.mechanic_ids:
            domain.append(('mechanic_id', 'in', self.mechanic_ids.ids))
        if self.inspection_type:
            domain.append(('inspection_type', '=', self.inspection_type))
        return domain

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('The start date must be before the end date.'))
        return self.env.ref('inspection.action_report_inspection_summary').report_action(self)

    def action_view_list(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inspections'),
            'res_model': 'fleet.inspection',
            'view_mode': 'list,form,graph,pivot',
            'domain': self._get_domain(),
        }
