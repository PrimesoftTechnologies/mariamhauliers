# -*- coding: utf-8 -*-
from odoo import api, models


class InspectionSummaryReport(models.AbstractModel):
    _name = 'report.inspection.report_inspection_summary'
    _description = 'Fleet Inspection Summary Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env['fleet.inspection.report.wizard'].browse(docids)
        wizard.ensure_one()
        Inspection = self.env['fleet.inspection']
        Line = self.env['fleet.inspection.line']
        inspections = Inspection.search(wizard._get_domain(), order='vehicle_id, date desc, id desc')
        defects = Line.search([
            ('inspection_id', 'in', inspections.ids), ('result', '=', 'defective')])

        result_count = {'pass': 0, 'pass_defects': 0, 'fail': 0}
        for rec in inspections:
            if rec.result in result_count:
                result_count[rec.result] += 1
        rated = sum(result_count.values())

        vehicles = []
        for vehicle, recs in inspections.grouped('vehicle_id').items():
            last = recs.sorted(lambda r: (r.date, r.id), reverse=True)[:1]
            vehicles.append({
                'vehicle': vehicle,
                'count': len(recs),
                'pass': len(recs.filtered(lambda r: r.result == 'pass')),
                'pass_defects': len(recs.filtered(lambda r: r.result == 'pass_defects')),
                'fail': len(recs.filtered(lambda r: r.result == 'fail')),
                'defects': sum(recs.mapped('defective_count')),
                'high': sum(recs.mapped('high_defect_count')),
                'avg_health': (sum(recs.mapped('health_score')) / len(recs)) if recs else 0.0,
                'last': last,
            })
        vehicles.sort(key=lambda v: (-v['fail'], -v['defects']))

        def top(groupby, limit=10):
            return Line._read_group(
                [('id', 'in', defects.ids)], [groupby], ['__count'], order='__count desc', limit=limit)

        mechanics = []
        for mechanic, recs in inspections.grouped('mechanic_id').items():
            durations = [d for d in recs.mapped('duration') if d]
            mechanics.append({
                'mechanic': mechanic,
                'count': len(recs),
                'defects': sum(recs.mapped('defective_count')),
                'avg_duration': (sum(durations) / len(durations)) if durations else 0.0,
            })
        mechanics.sort(key=lambda m: -m['count'])

        open_defects = defects.filtered(
            lambda l: l.severity == 'high' and (
                not l.job_card_id or l.job_card_id.state not in ('done', 'completed', 'cancel', 'cancelled')))

        return {
            'doc_ids': docids,
            'doc_model': 'fleet.inspection.report.wizard',
            'docs': wizard,
            'company': wizard.company_id,
            'inspections': inspections,
            'total': len(inspections),
            'result_count': result_count,
            'pass_rate': (100.0 * result_count['pass'] / rated) if rated else 0.0,
            'defect_total': len(defects),
            'high_total': len(defects.filtered(lambda l: l.severity == 'high')),
            'repeat_total': len(defects.filtered('is_repeat_defect')),
            'vehicles': vehicles,
            'top_categories': top('category_id'),
            'top_items': top('item_id'),
            'by_job_type': top('job_type_id'),
            'mechanics': mechanics,
            'open_high_defects': open_defects.sorted(lambda l: (l.vehicle_id.display_name or '', l.inspection_date)),
        }
