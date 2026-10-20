/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";

const PERIODS = [
    { days: 7, label: _t("7 days") },
    { days: 30, label: _t("30 days") },
    { days: 90, label: _t("90 days") },
    { days: 365, label: _t("12 months") },
];

const TABS = [
    { key: "inspection", label: _t("Inspections"), icon: "fa-clipboard" },
    { key: "workshop", label: _t("Workshop"), icon: "fa-wrench" },
    { key: "stores", label: _t("Stores & Tyres"), icon: "fa-cubes" },
];

const RESULT_LABELS = {
    pass: _t("Pass"),
    pass_defects: _t("Pass with defects"),
    fail: _t("Fail"),
};

const SEVERITY_LABELS = { low: _t("Low"), medium: _t("Medium"), high: _t("High") };

const COST_LABELS = { labour: _t("Labour"), parts: _t("Parts"), outside: _t("Outside service") };

const CLOSED_JOB_STATES = ["completed", "cancel"];

export class InspectionDashboard extends Component {
    static template = "inspection.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");
        this.chartRefs = {
            trend: useRef("trendChart"),
            category: useRef("categoryChart"),
            vehicle: useRef("vehicleChart"),
            jobType: useRef("jobTypeChart"),
            costTrend: useRef("costTrendChart"),
            jobState: useRef("jobStateChart"),
            costVehicle: useRef("costVehicleChart"),
            tyreRemoval: useRef("tyreRemovalChart"),
        };
        this.charts = {};
        this.periods = PERIODS;
        this.tabs = TABS;
        this.resultLabels = RESULT_LABELS;
        this.costLabels = COST_LABELS;
        this.state = useState({ days: 30, tab: "inspection", data: null, workshop: null, loading: true });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.fetchData();
        });
        useEffect(
            () => {
                this.renderCharts();
                return () => this.destroyCharts();
            },
            () => [this.state.data, this.state.workshop, this.state.tab]
        );
    }

    // ------------------------------------------------------------------ data
    async fetchData() {
        this.state.loading = true;
        if (this.state.tab === "inspection") {
            this.state.data = await this.orm.call("fleet.inspection", "get_dashboard_data", [], {
                days: this.state.days,
            });
        } else {
            this.state.workshop = await this.orm.call(
                "fleet.vehicle.log.services",
                "get_workshop_dashboard_data",
                [],
                { days: this.state.days }
            );
        }
        this.state.loading = false;
    }

    async setPeriod(days) {
        if (days === this.state.days) {
            return;
        }
        this.state.days = days;
        this.state.data = null;
        this.state.workshop = null;
        await this.refresh();
    }

    async setTab(tab) {
        if (tab === this.state.tab) {
            return;
        }
        this.state.tab = tab;
        const loaded = tab === "inspection" ? this.state.data : this.state.workshop;
        if (!loaded) {
            await this.fetchData();
        }
    }

    async refresh() {
        await this.fetchData();
    }

    get current() {
        return this.state.tab === "inspection" ? this.state.data : this.state.workshop;
    }

    get kpi() {
        return this.state.data.kpi;
    }

    get wk() {
        return this.state.workshop.kpi;
    }

    get resultTotal() {
        const k = this.kpi;
        return k.pass + k.pass_defects + k.fail;
    }

    get costTotal() {
        const k = this.wk;
        return k.labour_cost + k.parts_cost + k.outside_cost;
    }

    resultShare(key) {
        const total = this.resultTotal;
        return total ? Math.round((1000 * this.kpi[key]) / total) / 10 : 0;
    }

    costShare(key) {
        const total = this.costTotal;
        return total ? Math.round((1000 * this.wk[`${key}_cost`]) / total) / 10 : 0;
    }

    delta(current, previous, suffix = "") {
        const diff = Math.round((current - previous) * 10) / 10;
        if (!previous && !current) {
            return null;
        }
        return {
            value: `${diff > 0 ? "+" : ""}${diff}${suffix}`,
            direction: diff > 0 ? "up" : diff < 0 ? "down" : "flat",
        };
    }

    formatDate(value) {
        if (!value) {
            return _t("Never");
        }
        const [y, m, d] = value.split("-");
        return `${d}/${m}/${y}`;
    }

    formatAmount(value) {
        return Math.round(value || 0).toLocaleString();
    }

    // ------------------------------------------------------------- navigation
    get periodDomain() {
        const p = this.state.data.period;
        return [
            ["date", ">=", p.date_from],
            ["date", "<=", p.date_to],
            ["state", "!=", "cancel"],
        ];
    }

    get linePeriodDomain() {
        const p = this.state.data.period;
        return [
            ["inspection_date", ">=", p.date_from],
            ["inspection_date", "<=", p.date_to],
            ["inspection_state", "!=", "cancel"],
            ["result", "=", "defective"],
        ];
    }

    get completedDomain() {
        const p = this.state.workshop.period;
        return [
            ["state", "=", "completed"],
            ["completion_date", ">=", p.dt_from],
            ["completion_date", "<=", p.dt_to],
        ];
    }

    openList(resModel, name, domain, views = ["list", "form"], context = {}) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            views: views.map((v) => [false, v]),
            domain,
            context,
        });
    }

    openInspections(name, domain, extra = {}) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "fleet.inspection",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
                [false, "graph"],
                [false, "pivot"],
            ],
            domain,
            ...extra,
        });
    }

    openDefects(name, domain) {
        this.openList("fleet.inspection.line", name, domain, ["list", "pivot", "graph"]);
    }

    openJobs(name, domain) {
        this.openList("fleet.vehicle.log.services", name, domain, ["list", "kanban", "form", "pivot", "graph"]);
    }

    openRequests(name, domain) {
        this.openList("fleet.job.material.request", name, domain);
    }

    openLots(name, domain) {
        this.openList("stock.lot", name, [["fleet_part_type", "=", "tyre"], ...domain]);
    }

    openRecord(resModel, resId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
        });
    }

    onKpiClick(key) {
        if (key.startsWith("ws_") || key.startsWith("mr_") || key.startsWith("tyre_") || key === "po_open") {
            return this.onWorkshopKpiClick(key);
        }
        const period = this.periodDomain;
        switch (key) {
            case "total":
                return this.openInspections(_t("Inspections"), period);
            case "pass":
            case "pass_defects":
            case "fail":
                return this.openInspections(RESULT_LABELS[key], [...period, ["result", "=", key]]);
            case "to_approve":
                return this.openInspections(_t("To Approve"), [["state", "=", "completed"]]);
            case "in_progress":
                return this.openInspections(_t("Draft / In Progress"), [
                    ["state", "in", ["draft", "in_progress"]],
                ]);
            case "awaiting_job":
                return this.openDefects(_t("Defects without Job Card"), [
                    ["result", "=", "defective"],
                    ["job_card_id", "=", false],
                    ["inspection_state", "=", "approved"],
                ]);
            case "open_high":
                return this.openDefects(_t("Open High-Severity Defects"), [
                    ["result", "=", "defective"],
                    ["severity", "=", "high"],
                    ["inspection_state", "in", ["completed", "approved"]],
                    "|",
                    ["job_card_id", "=", false],
                    ["job_card_id.state", "not in", CLOSED_JOB_STATES],
                ]);
            case "open_jobs":
                return this.openJobs(_t("Open Job Cards"), [
                    ["inspection_id", "!=", false],
                    ["state", "not in", CLOSED_JOB_STATES],
                ]);
            case "fixed":
                return this.openDefects(_t("Repaired Defects"), [
                    ...this.linePeriodDomain,
                    ["repair_state", "=", "fixed"],
                ]);
            case "repeat_defects":
                return this.openDefects(_t("Repeat Defects"), [
                    ...this.linePeriodDomain,
                    ["is_repeat_defect", "=", true],
                ]);
            case "overdue":
                return this.openList("fleet.vehicle", _t("Vehicles Overdue for Inspection"), [
                    ["id", "in", this.state.data.overdue_ids],
                ]);
        }
    }

    onWorkshopKpiClick(key) {
        const open = [["state", "not in", CLOSED_JOB_STATES]];
        const jobStates = {
            ws_waiting_approval: "waiting_approval",
            ws_waiting_parts: "waiting_parts",
            ws_in_progress: "in_progress",
            ws_quality_check: "quality_check",
        };
        if (jobStates[key]) {
            const state = jobStates[key];
            const row = this.state.workshop.jobs_by_state.find((r) => r.id === state);
            return this.openJobs(row ? row.name : state, [["state", "=", state]]);
        }
        switch (key) {
            case "ws_open":
                return this.openJobs(_t("Open Job Cards"), open);
            case "ws_overdue":
                return this.openJobs(_t("Overdue Job Cards"), [["is_overdue", "=", true]]);
            case "ws_completed":
                return this.openJobs(_t("Completed Job Cards"), this.completedDomain);
            case "mr_to_approve":
                return this.openRequests(_t("Requests to Approve"), [["state", "=", "submitted"]]);
            case "mr_waiting":
                return this.openRequests(_t("Waiting Stock"), [["state", "in", ["approved", "waiting_stock"]]]);
            case "mr_ready":
                return this.openRequests(_t("Ready to Issue"), [["state", "=", "ready"]]);
            case "mr_issued":
                return this.openRequests(_t("Issued - usage to record"), [["state", "=", "issued"]]);
            case "mr_shortage":
                return this.openList("fleet.job.material.request.line", _t("Lines to Purchase"), [
                    ["open_purchase_qty", ">", 0],
                    ["request_state", "in", ["approved", "waiting_stock", "ready"]],
                ]);
            case "po_open":
                return this.openList("purchase.order", _t("Open Workshop RFQs"), [
                    ["workshop_material_request_id", "!=", false],
                    ["state", "in", ["draft", "sent", "to approve"]],
                ]);
            case "tyre_fitted":
                return this.openLots(_t("Fitted Tyres"), [["fleet_status", "=", "installed"]]);
            case "tyre_stock":
                return this.openLots(_t("Tyres in Stock"), [["fleet_status", "=", "in_stock"]]);
            case "tyre_retread":
                return this.openLots(_t("Tyres at Retreading"), [["fleet_status", "=", "retread"]]);
            case "tyre_due":
                return this.openLots(_t("Tyres Due for Replacement"), [
                    ["id", "in", this.state.workshop.tyres_due_ids],
                ]);
        }
    }

    newInspection(vehicleId = false) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("New Inspection"),
            res_model: "fleet.inspection",
            views: [[false, "form"]],
            context: vehicleId ? { default_vehicle_id: vehicleId } : {},
        });
    }

    openSummaryReport() {
        if (this.state.tab === "inspection") {
            this.action.doAction("inspection.action_fleet_inspection_report_wizard");
        } else {
            this.action.doAction("inspection.action_fleet_workshop_report_wizard");
        }
    }

    // ----------------------------------------------------------------- charts
    cssVar(name) {
        const el = this.rootRef.el;
        return el ? getComputedStyle(el).getPropertyValue(name).trim() : "";
    }

    destroyCharts() {
        for (const chart of Object.values(this.charts)) {
            chart.destroy();
        }
        this.charts = {};
    }

    baseOptions({ horizontal = false, stacked = false, legend = false } = {}) {
        const text = this.cssVar("--insp-text-secondary");
        const grid = this.cssVar("--insp-grid");
        const valueAxis = {
            stacked,
            beginAtZero: true,
            ticks: { precision: 0, color: text },
            grid: { color: grid, drawTicks: false },
            border: { display: false },
        };
        const categoryAxis = {
            stacked,
            ticks: { color: text, autoSkip: true, maxRotation: 0 },
            grid: { display: false },
            border: { color: grid },
        };
        return {
            indexAxis: horizontal ? "y" : "x",
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            interaction: { mode: horizontal ? "y" : "index", intersect: false },
            plugins: {
                legend: legend
                    ? {
                          position: "top",
                          align: "end",
                          labels: { color: text, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 2 },
                      }
                    : { display: false },
                tooltip: { padding: 8, boxPadding: 4, usePointStyle: true },
            },
            scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
            onHover: (event, elements) => {
                event.native.target.style.cursor = elements.length ? "pointer" : "default";
            },
        };
    }

    barDataset(label, data, color, extra = {}) {
        return {
            label,
            data,
            backgroundColor: color,
            hoverBackgroundColor: color,
            borderColor: this.cssVar("--insp-surface"),
            borderWidth: 1,
            borderRadius: 4,
            borderSkipped: "start",
            maxBarThickness: 28,
            ...extra,
        };
    }

    /** Single-series horizontal bar chart; onRow(row) is called on click. */
    singleBar(key, rows, label, valueKey, onRow) {
        const el = this.chartRefs[key].el;
        if (!el || !rows.length) {
            return;
        }
        this.charts[key] = new window.Chart(el, {
            type: "bar",
            data: {
                labels: rows.map((r) => r.name),
                datasets: [this.barDataset(label, rows.map((r) => r[valueKey]), this.cssVar("--insp-series-1"))],
            },
            options: {
                ...this.baseOptions({ horizontal: true }),
                onClick: (event, elements) => {
                    if (elements.length) {
                        onRow(rows[elements[0].index]);
                    }
                },
            },
        });
    }

    renderCharts() {
        this.destroyCharts();
        if (!window.Chart) {
            return;
        }
        if (this.state.tab === "inspection" && this.state.data) {
            this.renderInspectionCharts(this.state.data);
        } else if (this.state.tab === "workshop" && this.state.workshop && this.state.workshop.allowed) {
            this.renderWorkshopCharts(this.state.workshop);
        } else if (this.state.tab === "stores" && this.state.workshop && this.state.workshop.allowed) {
            this.renderStoresCharts(this.state.workshop);
        }
    }

    renderInspectionCharts(data) {
        const Chart = window.Chart;
        const statusColors = {
            pass: this.cssVar("--insp-good"),
            pass_defects: this.cssVar("--insp-warning"),
            fail: this.cssVar("--insp-critical"),
        };

        // Trend: inspections per period bucket, stacked by result
        const trendEl = this.chartRefs.trend.el;
        if (trendEl) {
            const trend = data.trend;
            this.charts.trend = new Chart(trendEl, {
                type: "bar",
                data: {
                    labels: trend.labels,
                    datasets: ["pass", "pass_defects", "fail"].map((key) =>
                        this.barDataset(RESULT_LABELS[key], trend.series[key], statusColors[key])
                    ),
                },
                options: {
                    ...this.baseOptions({ stacked: true, legend: true }),
                    onClick: (event, elements) => {
                        if (!elements.length) {
                            return;
                        }
                        const { index, datasetIndex } = elements[0];
                        const result = ["pass", "pass_defects", "fail"][datasetIndex];
                        const start = trend.starts[index];
                        const end = trend.starts[index + 1];
                        const domain = [["date", ">=", start], ["state", "!=", "cancel"], ["result", "=", result]];
                        domain.push(end ? ["date", "<", end] : ["date", "<=", data.period.date_to]);
                        this.openInspections(`${RESULT_LABELS[result]} - ${trend.labels[index]}`, domain);
                    },
                },
            });
        }

        // Defects by category, stacked by severity (ordinal ramp)
        const categoryEl = this.chartRefs.category.el;
        if (categoryEl && data.defects_by_category.length) {
            const rows = data.defects_by_category;
            const severityColors = {
                low: this.cssVar("--insp-ordinal-1"),
                medium: this.cssVar("--insp-ordinal-2"),
                high: this.cssVar("--insp-ordinal-3"),
            };
            this.charts.category = new Chart(categoryEl, {
                type: "bar",
                data: {
                    labels: rows.map((r) => r.name),
                    datasets: ["low", "medium", "high"].map((sev) =>
                        this.barDataset(
                            SEVERITY_LABELS[sev],
                            rows.map((r) => r[sev]),
                            severityColors[sev]
                        )
                    ),
                },
                options: {
                    ...this.baseOptions({ horizontal: true, stacked: true, legend: true }),
                    onClick: (event, elements) => {
                        if (elements.length) {
                            const row = rows[elements[0].index];
                            this.openDefects(_t("Defects - %s", row.name), [
                                ...this.linePeriodDomain,
                                ["category_id", "=", row.id],
                            ]);
                        }
                    },
                },
            });
        }

        const openDefectsOf = (field) => (row) =>
            this.openDefects(`${_t("Defects")} - ${row.name}`, [...this.linePeriodDomain, [field, "=", row.id || false]]);
        this.singleBar("vehicle", data.defects_by_vehicle, _t("Defects"), "count", openDefectsOf("vehicle_id"));
        this.singleBar("jobType", data.defects_by_job_type, _t("Defects"), "count", openDefectsOf("job_type_id"));
    }

    renderWorkshopCharts(data) {
        const Chart = window.Chart;
        // Cost over time, stacked labour / parts / outside (categorical slots 1-3)
        const costEl = this.chartRefs.costTrend.el;
        if (costEl) {
            const trend = data.cost_trend;
            const keys = ["labour", "parts", "outside"];
            const colors = {
                labour: this.cssVar("--insp-series-1"),
                parts: this.cssVar("--insp-series-2"),
                outside: this.cssVar("--insp-series-3"),
            };
            this.charts.costTrend = new Chart(costEl, {
                type: "bar",
                data: {
                    labels: trend.labels,
                    datasets: keys.map((key) => this.barDataset(COST_LABELS[key], trend.series[key], colors[key])),
                },
                options: {
                    ...this.baseOptions({ stacked: true, legend: true }),
                    onClick: (event, elements) => {
                        if (!elements.length) {
                            return;
                        }
                        const index = elements[0].index;
                        const start = `${trend.starts[index]} 00:00:00`;
                        const end = trend.starts[index + 1];
                        const domain = [["state", "=", "completed"], ["completion_date", ">=", start]];
                        domain.push(end ? ["completion_date", "<", `${end} 00:00:00`] : ["completion_date", "<=", data.period.dt_to]);
                        this.openJobs(`${_t("Completed")} - ${trend.labels[index]}`, domain);
                    },
                },
            });
        }
        this.singleBar("jobState", data.jobs_by_state, _t("Job cards"), "count", (row) =>
            this.openJobs(row.name, [["state", "=", row.id]])
        );
        this.singleBar("costVehicle", data.cost_by_vehicle, _t("Cost"), "cost", (row) =>
            this.openJobs(`${_t("Completed")} - ${row.name}`, [...this.completedDomain, ["vehicle_id", "=", row.id]])
        );
    }

    renderStoresCharts(data) {
        const p = data.period;
        this.singleBar("tyreRemoval", data.tyre_removals, _t("Tyres removed"), "count", (row) =>
            this.openList("fleet.vehicle.installed.part", `${_t("Tyres removed")} - ${row.name}`, [
                ["status", "=", "removed"],
                ["part_type", "=", "tyre"],
                ["remove_date", ">=", p.date_from],
                ["remove_date", "<=", p.date_to],
                ["removal_reason", "=", row.id],
            ])
        );
    }
}

registry.category("actions").add("inspection.dashboard", InspectionDashboard);
