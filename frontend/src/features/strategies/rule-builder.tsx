"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
import type { Condition, IndicatorName, IndicatorSpec, Operand, Operator, RuleSet } from "@/types/api";

import { defaultCondition, defaultOperand, describeCondition, INDICATOR_LABELS, OPERATOR_LABELS } from "./rules";

function OperandEditor({
  operand,
  catalog,
  allowValue,
  onChange,
}: {
  operand: Operand;
  catalog: IndicatorSpec[];
  allowValue: boolean;
  onChange: (o: Operand) => void;
}) {
  const isValue = operand.indicator == null;
  const spec = catalog.find((s) => s.name === operand.indicator);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Select
        value={isValue ? "__value" : (operand.indicator as string)}
        onValueChange={(v) => onChange(v === "__value" ? { value: 0 } : defaultOperand(v as IndicatorName, catalog))}
      >
        <SelectTrigger className="h-8 w-40 text-xs" aria-label="Indicator or value">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {allowValue && <SelectItem value="__value">Number</SelectItem>}
          {catalog.map((s) => (
            <SelectItem key={s.name} value={s.name}>
              {INDICATOR_LABELS[s.name]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isValue ? (
        <Input
          type="number"
          step="any"
          aria-label="Value"
          className="h-8 w-24 text-xs"
          value={Number.isFinite(operand.value) ? String(operand.value) : ""}
          onChange={(e) => onChange({ value: e.target.value === "" ? Number.NaN : Number(e.target.value) })}
        />
      ) : (
        <>
          {spec &&
            Object.entries(spec.params).map(([name, p]) => (
              <label key={name} className="flex items-center gap-1 text-[11px] text-muted-foreground">
                {name}
                <Input
                  type="number"
                  min={p.min}
                  max={p.max}
                  step={name === "std" ? 0.1 : 1}
                  className="h-8 w-16 text-xs"
                  value={operand.params?.[name] ?? p.default}
                  onChange={(e) => onChange({ ...operand, params: { ...operand.params, [name]: Number(e.target.value) } })}
                />
              </label>
            ))}
          {spec && spec.fields.length > 0 && (
            <Select value={operand.field ?? spec.fields[0]} onValueChange={(f) => onChange({ ...operand, field: f })}>
              <SelectTrigger className="h-8 w-24 text-xs" aria-label="Indicator output">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {spec.fields.map((f) => (
                  <SelectItem key={f} value={f}>
                    {f.replace("_", " ")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </>
      )}
    </div>
  );
}

function ConditionRow({
  condition,
  catalog,
  onChange,
  onRemove,
}: {
  condition: Condition;
  catalog: IndicatorSpec[];
  onChange: (c: Condition) => void;
  onRemove: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-background-elevated/50 p-3">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
        <OperandEditor operand={condition.left} catalog={catalog} allowValue={false} onChange={(left) => onChange({ ...condition, left })} />
        <Select value={condition.op} onValueChange={(op) => onChange({ ...condition, op: op as Operator })}>
          <SelectTrigger className="h-8 w-36 text-xs" aria-label="Comparison">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(OPERATOR_LABELS) as Operator[]).map((op) => (
              <SelectItem key={op} value={op}>
                {OPERATOR_LABELS[op]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <OperandEditor operand={condition.right} catalog={catalog} allowValue onChange={(right) => onChange({ ...condition, right })} />
        <Button variant="ghost" size="icon-sm" className="ml-auto text-muted-foreground hover:text-loss" onClick={onRemove} aria-label="Remove condition">
          <Trash2 />
        </Button>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">{describeCondition(condition)}</p>
    </div>
  );
}

export function RuleSetBuilder({
  title,
  description,
  rules,
  catalog,
  onChange,
}: {
  title: string;
  description: string;
  rules: RuleSet;
  catalog: IndicatorSpec[];
  onChange: (r: RuleSet) => void;
}) {
  const update = (i: number, c: Condition) => onChange({ ...rules, conditions: rules.conditions.map((x, j) => (j === i ? c : x)) });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        <Segmented value={rules.logic} onValueChange={(v) => onChange({ ...rules, logic: v as RuleSet["logic"] })} label="Condition logic" className="h-8">
            <SegmentedItem value="all" className="h-6 text-[11px]">
              Match ALL
            </SegmentedItem>
            <SegmentedItem value="any" className="h-6 text-[11px]">
              Match ANY
            </SegmentedItem>
          </Segmented>
      </div>
      {rules.conditions.length === 0 && (
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">No conditions yet.</p>
      )}
      {rules.conditions.map((c, i) => (
        <ConditionRow
          key={i}
          condition={c}
          catalog={catalog}
          onChange={(nc) => update(i, nc)}
          onRemove={() => onChange({ ...rules, conditions: rules.conditions.filter((_, j) => j !== i) })}
        />
      ))}
      <Button
        variant="outline"
        size="sm"
        disabled={rules.conditions.length >= 10}
        onClick={() => onChange({ ...rules, conditions: [...rules.conditions, defaultCondition(catalog)] })}
      >
        <Plus /> Add condition
      </Button>
    </div>
  );
}
