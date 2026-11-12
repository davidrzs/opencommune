export type Commune = {
  bfs_id: number;
  name: string;
  canton: string;
  documents: number;
  decisions: number;
  // from the dataset (/api/dataset/coverage), merged in on the start page
  minutes?: number;
  counted?: number;
  finance_years?: number;
  lat?: number | null;
  lon?: number | null;
  website?: string;
  access?: {
    status: 'restricted' | 'rate_limited' | 'robots_unavailable' | 'technical_error';
    checked_at: string;
    restricted_at: string | null;
    stale: boolean;
    robots_url: string;
    source_url: string;
  }[];
  holdings?: { last_crawl?: string; first_date?: string; last_date?: string }[];
};
export const normalize = (s: string) =>
  s
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
export type Findings = {
  deficits: { year: number; type: 'budget' | 'accounts'; deficit: number; n: number }[];
  turnout_by_size: { min: number; max: number | null; median: number | null; n: number }[];
};
export type DatasetVote = {
  meeting_date: string | null;
  body: string;
  motion: number;
  motion_kind: string | null;
  title: string | null;
  title_withheld: number;
  outcome: string | null;
  vote_method: string | null;
  votes_yes: number | null;
  votes_no: number | null;
  counts_agree: number | null;
  formal: boolean;
  sha256: string;
};
export type DatasetFinance = {
  fiscal_year: number;
  type: 'budget' | 'accounts';
  operating_result: number | null;
  tax_rate_percent: number | null;
  result_agrees: number | null;
  source_url: string | null;
};
export type CommuneDataset = {
  meetings: { meeting_date: string | null; body: string; turnout: number | null }[];
  votes: DatasetVote[];
  finance: DatasetFinance[];
  summary: {
    meetings: number;
    median_turnout: number | null;
    counted: number;
    decided: number;
    rejected: number;
  };
};

export type Coverage = {
  communes: { bfs_id: number; minutes: number; counted: number; finance_years: number }[];
  totals: {
    communes: number;
    communes_with_minutes: number;
    communes_with_finance: number;
    population_share: number | null;
    minutes: number;
    counted: number;
  };
};

// votes or finances captured, from the archive or the dataset
export const hasData = (c: Commune) =>
  c.decisions > 0 || (c.minutes ?? 0) > 0 || (c.finance_years ?? 0) > 0;
export const hasDocuments = (c: Commune) => c.documents > 0;
