-- ============================================================
-- Tutors & Student Assignment Workflow - Database Migration
-- Run this in Supabase SQL Editor to apply all changes
-- ============================================================

-- Step 1: Add tutor agreement tracking columns
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS agreement_accepted BOOLEAN DEFAULT FALSE;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS agreement_accepted_at TIMESTAMPTZ;

-- Step 2: Link lab tokens to assignments
ALTER TABLE public.lab_tokens ADD COLUMN IF NOT EXISTS assignment_id UUID REFERENCES public.assignments(id) ON DELETE SET NULL;

-- Step 3: Create index for better query performance
CREATE INDEX IF NOT EXISTS idx_lab_tokens_assignment ON public.lab_tokens(assignment_id);
CREATE INDEX IF NOT EXISTS idx_tutors_agreement ON public.tutors(agreement_accepted);

-- Step 4: Verify changes
-- Run these queries to verify the migration completed:
-- SELECT * FROM tutors LIMIT 1;
-- SELECT * FROM lab_tokens LIMIT 1;
-- \d tutors   (shows columns)
-- \d lab_tokens (shows columns)

-- ============================================================
-- Optional: Add check constraints for data quality
-- ============================================================
ALTER TABLE public.tutors 
ADD CONSTRAINT agreement_accepted_consistency 
CHECK (
  (agreement_accepted = TRUE AND agreement_accepted_at IS NOT NULL) OR
  (agreement_accepted = FALSE AND agreement_accepted_at IS NULL)
);

-- ============================================================
-- Success! All migrations applied.
-- You can now use the new endpoints:
-- - GET/PATCH /tutors/me/availability
-- - POST /tutors/me/agreement
-- - POST /sessions/my/book
-- - POST /sessions/{id}/webhook
-- - POST /lab/tokens (with assignment validation)
-- ============================================================
