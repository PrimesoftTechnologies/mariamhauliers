# -*- coding: utf-8 -*-
from odoo import _, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    workshop_material_request_id = fields.Many2one('fleet.job.material.request', string='Material Request',
                                                   index=True, copy=False)
    fleet_job_id = fields.Many2one(related='workshop_material_request_id.job_id', string='Job Card')
    fleet_vehicle_id = fields.Many2one(related='workshop_material_request_id.vehicle_id', string='Vehicle',
                                       store=True)

    def button_confirm(self):
        res = super().button_confirm()
        for order in self.filtered('workshop_material_request_id'):
            order.workshop_material_request_id.sudo().message_post(
                body=_('Purchase order %s confirmed with %s.', order.name, order.partner_id.display_name))
        return res


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    material_request_line_id = fields.Many2one('fleet.job.material.request.line', string='Material Request Line',
                                               index=True, copy=False)
