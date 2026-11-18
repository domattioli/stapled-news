create table if not exists public.headlines (
  url text primary key,
  domain text not null,
  title text not null,
  seendate text,
  source text,
  first_seen_at timestamptz default now()
);

create index if not exists headlines_domain_idx on public.headlines (domain);
create index if not exists headlines_seendate_idx on public.headlines (seendate);

-- RLS on, no policies: only the service role (which bypasses RLS) can access.
alter table public.headlines enable row level security;
