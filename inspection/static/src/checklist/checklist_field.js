/** @odoo-module **/

import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useState, useSubEnv } from "@odoo/owl";

function m2oName(value) {
    if (!value) {
        return "";
    }
    return Array.isArray(value) ? value[1] || "" : value.display_name || "";
}

function m2oId(value) {
    if (!value) {
        return false;
    }
    return Array.isArray(value) ? value[0] : value.id;
}

/**
 * Checklist filter state shared between the field (toolbar) and its list renderer.
 */
function matchesFilter(filter, record) {
    if (record.isInEdition || record.isNew) {
        return true; // never hide the row the user is typing in
    }
    const data = record.data;
    if (filter.result !== "all" && data.result !== filter.result) {
        return false;
    }
    if (filter.categoryId && m2oId(data.category_id) !== filter.categoryId) {
        return false;
    }
    const query = (filter.search || "").trim().toLowerCase();
    if (query) {
        const haystack = [
            m2oName(data.category_id),
            m2oName(data.item_id),
            m2oName(data.lot_id),
            data.comment || "",
        ]
            .join(" ")
            .toLowerCase();
        return query.split(/\s+/).every((word) => haystack.includes(word));
    }
    return true;
}

export class ChecklistListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.checklistFilter = useState(this.env.inspectionChecklistFilter);
    }

    getRowClass(record) {
        const classes = super.getRowClass(record);
        return matchesFilter(this.checklistFilter, record) ? classes : `${classes} d-none`;
    }
}

export class InspectionChecklistField extends X2ManyField {
    static template = "inspection.ChecklistField";
    static components = { ...X2ManyField.components, ListRenderer: ChecklistListRenderer };

    setup() {
        super.setup();
        this.filter = useState({ search: "", result: "all", categoryId: false });
        useSubEnv({ inspectionChecklistFilter: this.filter });
    }

    get records() {
        return this.list.records;
    }

    get categories() {
        const seen = new Map();
        for (const record of this.records) {
            const id = m2oId(record.data.category_id);
            if (id && !seen.has(id)) {
                seen.set(id, { id, name: m2oName(record.data.category_id), total: 0, defective: 0 });
            }
            if (id) {
                const entry = seen.get(id);
                entry.total++;
                if (record.data.result === "defective") {
                    entry.defective++;
                }
            }
        }
        return [...seen.values()];
    }

    get counts() {
        const counts = { all: 0, good: 0, defective: 0, na: 0 };
        for (const record of this.records) {
            counts.all++;
            if (record.data.result in counts) {
                counts[record.data.result]++;
            }
        }
        return counts;
    }

    get visibleCount() {
        return this.records.filter((record) => matchesFilter(this.filter, record)).length;
    }

    get isFiltered() {
        return Boolean(this.filter.search || this.filter.categoryId || this.filter.result !== "all");
    }

    setResult(result) {
        this.filter.result = result;
    }

    onCategoryChange(ev) {
        this.filter.categoryId = parseInt(ev.target.value) || false;
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault(); // don't submit / save the form
        } else if (ev.key === "Escape") {
            this.filter.search = "";
        }
    }

    clearFilters() {
        Object.assign(this.filter, { search: "", result: "all", categoryId: false });
    }
}

registry.category("fields").add("inspection_checklist", {
    ...x2ManyField,
    component: InspectionChecklistField,
});
