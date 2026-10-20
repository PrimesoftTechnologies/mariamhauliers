# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    inspection_overdue_days = fields.Integer(
        string='Inspection Interval (days)', config_parameter='inspection.overdue_days', default=7,
        help='A vehicle without inspection for longer is shown as overdue on the dashboard.')
    inspection_job_manager_approval_amount = fields.Float(
        string='Fleet Manager Approval Above', config_parameter='inspection.job_manager_approval_amount',
        help='Job cards estimated above this amount must be approved by a Fleet Manager. 0 = no limit.')
    inspection_mr_purchase_mode = fields.Selection([
        ('auto', 'Automatically create RFQs for the shortage'),
        ('manual', 'Procurement Officer creates the purchase'),
    ], string='Material Shortage', config_parameter='inspection.mr_purchase_mode', default='auto')
    inspection_tyre_wear_warning_pct = fields.Float(
        string='Tyre Replacement Warning (% of life)', config_parameter='inspection.tyre_wear_warning_pct',
        default=90.0)
