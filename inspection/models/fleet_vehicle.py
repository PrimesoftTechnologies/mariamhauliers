# -*- coding: utf-8 -*-
from odoo import fields, models, _

from .fleet_inspection import CLOSED_JOB_STATES


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    # --- Inspections -----------------------------------------------------------
    inspection_ids = fields.One2many('fleet.inspection', 'vehicle_id', string='Inspections')
    inspection_count = fields.Integer(compute='_compute_inspection_info')
    last_inspection_date = fields.Date(compute='_compute_inspection_info', string='Last Inspection')
    last_inspection_result = fields.Selection([
        ('pass', 'Pass'),
        ('pass_defects', 'Pass with Defects'),
        ('fail', 'Fail'),
    ], compute='_compute_inspection_info', string='Last Inspection Result')

    # --- Workshop --------------------------------------------------------------
    job_card_count = fields.Integer(compute='_compute_workshop_info')
    open_job_card_count = fields.Integer(compute='_compute_workshop_info', string='Open Job Cards')
    maintenance_cost = fields.Float(compute='_compute_workshop_info', string='Maintenance Cost',
                                    help='Total cost of the completed job cards.')

    # --- Fitted parts (tyres, batteries...) ------------------------------------
    installed_part_ids = fields.One2many('fleet.vehicle.installed.part', 'vehicle_id', string='Part History')
    current_part_ids = fields.One2many('fleet.vehicle.installed.part', 'vehicle_id', string='Fitted Parts',
                                       domain=[('status', '=', 'installed')])
    installed_part_count = fields.Integer(compute='_compute_installed_part_count')

    def _compute_inspection_info(self):
        Inspection = self.env['fleet.inspection']
        counts = dict(Inspection._read_group(
            [('vehicle_id', 'in', self.ids)], ['vehicle_id'], ['__count']))
        for vehicle in self:
            last = Inspection.search([
                ('vehicle_id', '=', vehicle.id), ('state', 'in', ('completed', 'approved')),
            ], order='date desc, id desc', limit=1) if vehicle.id else Inspection
            vehicle.inspection_count = counts.get(vehicle, 0)
            vehicle.last_inspection_date = last.date
            vehicle.last_inspection_result = last.result

    def _compute_workshop_info(self):
        Service = self.env['fleet.vehicle.log.services']
        counts = dict(Service._read_group([('vehicle_id', 'in', self.ids)], ['vehicle_id'], ['__count']))
        open_counts = dict(Service._read_group(
            [('vehicle_id', 'in', self.ids), ('state', 'not in', CLOSED_JOB_STATES)], ['vehicle_id'], ['__count']))
        costs = dict(Service._read_group(
            [('vehicle_id', 'in', self.ids), ('state', '=', 'completed')], ['vehicle_id'], ['actual_cost:sum']))
        for vehicle in self:
            vehicle.job_card_count = counts.get(vehicle, 0)
            vehicle.open_job_card_count = open_counts.get(vehicle, 0)
            vehicle.maintenance_cost = costs.get(vehicle, 0.0) or 0.0

    def _compute_installed_part_count(self):
        counts = dict(self.env['fleet.vehicle.installed.part']._read_group(
            [('vehicle_id', 'in', self.ids), ('status', '=', 'installed')], ['vehicle_id'], ['__count']))
        for vehicle in self:
            vehicle.installed_part_count = counts.get(vehicle, 0)

    def action_view_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inspections'),
            'res_model': 'fleet.inspection',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_new_inspection(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Inspection'),
            'res_model': 'fleet.inspection',
            'view_mode': 'form',
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_installed_parts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fitted Parts'),
            'res_model': 'fleet.vehicle.installed.part',
            'view_mode': 'list,form,pivot',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id, 'search_default_installed': 1},
        }

    def action_view_job_cards(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Job Cards'),
            'res_model': 'fleet.vehicle.log.services',
            'view_mode': 'list,kanban,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }
