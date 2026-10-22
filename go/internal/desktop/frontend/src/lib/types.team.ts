// Types of the bindings of the Team area (go/internal/app/api_team*.go, api_rules.go).

export interface RuleOwner {
  kind: 'product' | 'project' | 'setting';
  id: string;
}

export interface RulePreview {
  valid: boolean;
  error?: string;
  /** Place of the problem in the text (0-based), -1 if unknown. */
  pos: number;
  /** The rule as Foresprint writes it. */
  normalized?: string;
  fields: string[];
  matches: number;
  points: number;
  sample: string[];
  clash: number;
  moved: number;
}

export interface TeamApi {
  RuleFields(team: string): Promise<string[]>;
  CheckRule(team: string, text: string, owner: RuleOwner): Promise<RulePreview>;
}
