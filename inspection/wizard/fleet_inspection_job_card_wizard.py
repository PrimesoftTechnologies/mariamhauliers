# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class FleetInspectionJobCardWizard(models.TransientModel):
    _name = 'fleet.inspection.job.card.wizard'
    _description = 'Create Job Cards from Inspection'

    inspection_id = fields.Many2one('fleet.inspection', required=True, ondelete='cascade')
    vehicle_id = fields.Many2one(related='inspection_id.vehicle_id')
    split_mode = fields.Selection([
        ('job_type', 'One job card per job type'),
        ('single', 'One job card for all selected defects'),
    ], default='job_type', required=True, string='Create')
    single_job_type_id = fields.Many2one(
        'fleet.inspection.job.type', string='Job Type',
        help='Job type of the single job card.')
    line_ids = fields.One2many('fleet.inspection.job.card.wizard.line', 'wizard_id', string='Defects')
    summary = fields.Html(compute='_compute_summary')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        inspection = self.env['fleet.inspection'].browse(
            res.get('inspection_id') or self.env.context.get('active_id'))
        if inspection:
            res['inspection_id'] = inspection.id
            defects = inspection.line_ids.filtered(
                lambda l: l.result == 'defective' and not l.job_card_id)
            res['line_ids'] = [fields.Command.create({
                'inspection_line_id': line.id,
                'job_type_id': line.job_type_id.id,
                'selected': True,
            }) for line in defects]
        return res

    @api.depends('line_ids.selected', 'line_ids.job_type_id', 'split_mode', 'single_job_type_id')
    def _compute_summary(self):
        for wizard in self:
            selected = wizard.line_ids.filtered('selected')
            if not selected:
                wizard.summary = Markup('<p class="text-warning mb-0">%s</p>') % _('No defect selected.')
                continue
            if wizard.split_mode == 'single':
                label = wizard.single_job_type_id.name or _('General')
                parts = [Markup('<li><b>%s</b>: %s</li>') % (label, _('%s defect(s)', len(selected)))]
            else:
                groups = {}
                for line in selected:
                    groups.setdefault(line.job_type_id.name or _('Unassigned'), 0)
                    groups[line.job_type_id.name or _('Unassigned')] += 1
                parts = [Markup('<li><b>%s</b>: %s</li>') % (name, _('%s defect(s)', count))
                         for name, count in groups.items()]
            count = len(parts)
            wizard.summary = Markup('<p class="mb-1">%s</p><ul class="mb-0">%s</ul>') % (
                _('%s job card(s) will be created:', count), Markup('').join(parts))

    def action_select_all(self):
        self.line_ids.write({'selected': True})
        return self._reopen()

    def action_select_none(self):
        self.line_ids.write({'selected': False})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Create Job Cards'),
        }

    def action_create(self):
        self.ensure_one()
        inspection = self.inspection_id
        if inspection.state != 'approved':
            raise UserError(_('Job cards can only be created from approved inspections.'))
        selected = self.line_ids.filtered('selected')
        if not selected:
            raise UserError(_('Select at least one defect.'))
        # Persist any re-classification made in the wizard on the inspection lines
        for wline in selected:
            if wline.inspection_line_id.job_type_id != wline.job_type_id:
                wline.inspection_line_id.job_type_id = wline.job_type_id
        groups = {}
        JobType = self.env['fleet.inspection.job.type']
        for wline in selected:
            key = self.single_job_type_id if self.split_mode == 'single' else wline.job_type_id
            groups.setdefault(key or JobType, self.env['fleet.inspection.line'])
            groups[key or JobType] |= wline.inspection_line_id
        services = inspection._create_job_cards(groups)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Job Cards'),
            'res_model': 'fleet.vehicle.log.services',
            'view_mode': 'list,form' if len(services) > 1 else 'form',
            'res_id': services.id if len(services) == 1 else False,
            'domain': [('id', 'in', services.ids)],
        }


class FleetInspectionJobCardWizardLine(models.TransientModel):
    _name = 'fleet.inspection.job.card.wizard.line'
    _description = 'Create Job Cards - Defect Line'

    wizard_id = fields.Many2one('fleet.inspection.job.card.wizard', required=True, ondelete='cascade')
    inspection_line_id = fields.Many2one('fleet.inspection.line', required=True, ondelete='cascade')
    selected = fields.Boolean(string='Include', default=True)
    category_id = fields.Many2one(related='inspection_line_id.category_id')
    item_id = fields.Many2one(related='inspection_line_id.item_id')
    severity = fields.Selection(related='inspection_line_id.severity')
    comment = fields.Char(related='inspection_line_id.comment')
    is_repeat_defect = fields.Boolean(related='inspection_line_id.is_repeat_defect')
    job_type_id = fields.Many2one('fleet.inspection.job.type', string='Job Type')
