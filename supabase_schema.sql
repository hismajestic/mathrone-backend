-- ============================================================
-- TutorConnect Academy — Supabase PostgreSQL Schema
-- Run this ONCE in your Supabase SQL Editor
-- Dashboard → SQL Editor → New Query → Paste → Run
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- ENUMS
-- ============================================================
DO $$ BEGIN
  CREATE TYPE user_role         AS ENUM ('student', 'tutor', 'admin');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE tutor_status      AS ENUM ('applicant', 'under_review', 'written_exam', 'interview', 'approved', 'rejected', 'suspended');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE session_mode      AS ENUM ('online', 'home');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE session_status    AS ENUM ('pending', 'scheduled', 'in_progress', 'completed', 'cancelled');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE request_status    AS ENUM ('pending', 'assigned', 'rejected');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE payment_status    AS ENUM ('pending', 'paid', 'overdue', 'refunded');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE message_status    AS ENUM ('sent', 'delivered', 'read');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE notification_type AS ENUM ('session_reminder', 'tutor_assigned', 'new_message', 'application_update', 'payment_due', 'general');
  EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- PROFILES  (extends Supabase auth.users)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.profiles (
    id          UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name   TEXT        NOT NULL,
    email       TEXT        NOT NULL UNIQUE,
    phone       TEXT,
    role        user_role   NOT NULL DEFAULT 'student',
    avatar_url  TEXT,
    is_active   BOOLEAN     DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- STUDENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.students (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id      UUID        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    school_level    TEXT        NOT NULL,
    subjects_needed TEXT[]      NOT NULL DEFAULT '{}',
    preferred_mode  session_mode NOT NULL DEFAULT 'online',
    home_location   TEXT,
    home_lat        DECIMAL(10,8),
    home_lng        DECIMAL(11,8),
    parent_name     TEXT,
    parent_phone    TEXT,
    category        TEXT        NOT NULL DEFAULT 'academic',
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TUTORS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.tutors (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id          UUID        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    status              tutor_status NOT NULL DEFAULT 'applicant',
    subjects            TEXT[]      NOT NULL DEFAULT '{}',
    levels              TEXT[]      NOT NULL DEFAULT '{}',
    teaching_mode       session_mode,
    teaching_modes      TEXT[]      DEFAULT '{}',
    experience_years    INTEGER     DEFAULT 0,
    experience_desc     TEXT,
    qualification       TEXT        NOT NULL DEFAULT '',
    education_details   JSONB       DEFAULT '[]',
    languages           TEXT[]      DEFAULT '{"English"}',
    bio                 TEXT,
    cv_url              TEXT,
    certificate_urls    TEXT[]      DEFAULT '{}',
    hourly_rate         DECIMAL(10,2),
    availability        JSONB       DEFAULT '{}',
    location            TEXT,
    lat                 DECIMAL(10,8),
    lng                 DECIMAL(11,8),
    rating              DECIMAL(3,2) DEFAULT 0,
    total_reviews       INTEGER     DEFAULT 0,
    total_sessions      INTEGER     DEFAULT 0,
    is_available        BOOLEAN     DEFAULT TRUE,
    admin_notes         TEXT,
    reviewed_by         UUID        REFERENCES public.profiles(id),
    reviewed_at         TIMESTAMPTZ,
    exam_score          INTEGER,
    interview_notes     TEXT,
    approved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TUTOR-STUDENT ASSIGNMENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.assignments (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id  UUID        NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    tutor_id    UUID        NOT NULL REFERENCES public.tutors(id)   ON DELETE CASCADE,
    subject     TEXT        NOT NULL,
    mode        session_mode NOT NULL,
    assigned_by UUID        REFERENCES public.profiles(id),
    is_active   BOOLEAN     DEFAULT TRUE,
    notes       TEXT,
    start_date  DATE        DEFAULT CURRENT_DATE,
    end_date    DATE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (student_id, tutor_id, subject)
);

-- ============================================================
-- TUTORING REQUESTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.tutoring_requests (
    id              UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id      UUID           NOT NULL REFERENCES public.students(id),
    subject         TEXT           NOT NULL,
    level           TEXT           NOT NULL,
    mode            session_mode   NOT NULL,
    preferred_days  TEXT[]         DEFAULT '{}',
    preferred_time  TEXT,
    home_location   TEXT,
    notes           TEXT,
    status          request_status DEFAULT 'pending',
    assigned_tutor  UUID           REFERENCES public.tutors(id),
    handled_by      UUID           REFERENCES public.profiles(id),
    created_at      TIMESTAMPTZ    DEFAULT NOW(),
    updated_at      TIMESTAMPTZ    DEFAULT NOW()
);

-- ============================================================
-- SESSIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.sessions (
    id               UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    assignment_id    UUID           REFERENCES public.assignments(id),
    student_id       UUID           NOT NULL REFERENCES public.students(id),
    tutor_id         UUID           NOT NULL REFERENCES public.tutors(id),
    subject          TEXT           NOT NULL,
    mode             session_mode   NOT NULL,
    status           session_status DEFAULT 'scheduled',
    scheduled_at     TIMESTAMPTZ    NOT NULL,
    duration_mins    INTEGER        DEFAULT 60,
    actual_start     TIMESTAMPTZ,
    actual_end       TIMESTAMPTZ,
    meeting_link     TEXT,
    meeting_id       TEXT,
    meeting_password TEXT,
    platform         TEXT,
    location         TEXT,
    notes            TEXT,
    tutor_notes      TEXT,
    student_rating   INTEGER        CHECK (student_rating BETWEEN 1 AND 5),
    student_review   TEXT,
    materials_urls   TEXT[]         DEFAULT '{}',
    cancelled_by     UUID           REFERENCES public.profiles(id),
    cancel_reason    TEXT,
    created_at       TIMESTAMPTZ    DEFAULT NOW(),
    updated_at       TIMESTAMPTZ    DEFAULT NOW()
);

-- ============================================================
-- PAYMENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.payment_packages (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name       TEXT        NOT NULL,
    sessions   INTEGER     NOT NULL,
    price      DECIMAL(10,2) NOT NULL,
    level      TEXT,
    is_active  BOOLEAN     DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.invoices (
    id          UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    student_id  UUID           NOT NULL REFERENCES public.students(id),
    package_id  UUID           REFERENCES public.payment_packages(id),
    amount      DECIMAL(10,2)  NOT NULL,
    currency    TEXT           DEFAULT 'USD',
    status      payment_status DEFAULT 'pending',
    due_date    DATE,
    paid_at     TIMESTAMPTZ,
    payment_ref TEXT,
    notes       TEXT,
    issued_by   UUID           REFERENCES public.profiles(id),
    created_at  TIMESTAMPTZ    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.tutor_salaries (
    id             UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    tutor_id       UUID           NOT NULL REFERENCES public.tutors(id),
    period_start   DATE           NOT NULL,
    period_end     DATE           NOT NULL,
    sessions_count INTEGER        DEFAULT 0,
    amount         DECIMAL(10,2)  NOT NULL,
    status         payment_status DEFAULT 'pending',
    paid_at        TIMESTAMPTZ,
    payment_ref    TEXT,
    created_at     TIMESTAMPTZ    DEFAULT NOW()
);

-- ============================================================
-- MESSAGING
-- ============================================================
CREATE TABLE IF NOT EXISTS public.conversations (
    id               UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    participant_a    UUID        NOT NULL REFERENCES public.profiles(id),
    participant_b    UUID        NOT NULL REFERENCES public.profiles(id),
    last_message     TEXT,
    last_message_at  TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (participant_a, participant_b)
);

CREATE TABLE IF NOT EXISTS public.messages (
    id               UUID           PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id  UUID           NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    sender_id        UUID           NOT NULL REFERENCES public.profiles(id),
    content          TEXT           NOT NULL,
    status           message_status DEFAULT 'sent',
    attachment_url   TEXT,
    created_at       TIMESTAMPTZ    DEFAULT NOW()
);

-- ============================================================
-- NOTIFICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.notifications (
    id         UUID              PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID              NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    type       notification_type NOT NULL,
    title      TEXT              NOT NULL,
    body       TEXT              NOT NULL,
    data       JSONB             DEFAULT '{}',
    is_read    BOOLEAN           DEFAULT FALSE,
    created_at TIMESTAMPTZ       DEFAULT NOW()
);

-- ============================================================
-- REVIEWS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.reviews (
    id          UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  UUID    NOT NULL REFERENCES public.sessions(id),
    student_id  UUID    NOT NULL REFERENCES public.students(id),
    tutor_id    UUID    NOT NULL REFERENCES public.tutors(id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (session_id)
);

-- ============================================================
-- NEWS POSTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.news_posts (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    title           TEXT        NOT NULL,
    content         TEXT        NOT NULL,
    category        TEXT        NOT NULL DEFAULT 'news',
    tags            TEXT[]      DEFAULT '{}',
    image_url       TEXT,
    source_url      TEXT,
    source_name     TEXT,
    is_featured     BOOLEAN     DEFAULT FALSE,
    views_count     INTEGER     DEFAULT 0,
    published_by    UUID        REFERENCES public.profiles(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Add SEO fields to news_posts table
ALTER TABLE public.news_posts ADD COLUMN IF NOT EXISTS slug TEXT UNIQUE;
ALTER TABLE public.news_posts ADD COLUMN IF NOT EXISTS description TEXT;

-- Create index on slug for faster lookups
CREATE INDEX IF NOT EXISTS idx_news_posts_slug ON public.news_posts(slug);

-- ============================================================
-- NEWSLETTER SUBSCRIPTIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.newsletter_subscriptions (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       TEXT        NOT NULL UNIQUE,
    is_active   BOOLEAN     DEFAULT TRUE,
    subscribed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SEED: Default payment packages
-- ============================================================
INSERT INTO public.payment_packages (name, sessions, price, level) VALUES
    ('Primary — 4 Sessions',    4,  100.00, 'Primary'),
    ('Primary — 8 Sessions',    8,  190.00, 'Primary'),
    ('Secondary — 4 Sessions',  4,  140.00, 'Secondary'),
    ('Secondary — 8 Sessions',  8,  270.00, 'Secondary'),
    ('University — 4 Sessions', 4,  200.00, 'University'),
    ('University — 8 Sessions', 8,  380.00, 'University')
ON CONFLICT DO NOTHING;

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_sessions_student    ON public.sessions(student_id);
CREATE INDEX IF NOT EXISTS idx_sessions_tutor      ON public.sessions(tutor_id);
CREATE INDEX IF NOT EXISTS idx_sessions_scheduled  ON public.sessions(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status     ON public.sessions(status);
CREATE INDEX IF NOT EXISTS idx_messages_conv       ON public.messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_user  ON public.notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_tutors_status       ON public.tutors(status);
CREATE INDEX IF NOT EXISTS idx_tutors_subjects     ON public.tutors USING GIN(subjects);
CREATE INDEX IF NOT EXISTS idx_students_profile    ON public.students(profile_id);
CREATE INDEX IF NOT EXISTS idx_tutors_profile      ON public.tutors(profile_id);
CREATE INDEX IF NOT EXISTS idx_assignments_student ON public.assignments(student_id, is_active);
CREATE INDEX IF NOT EXISTS idx_news_posts_category ON public.news_posts(category);
CREATE INDEX IF NOT EXISTS idx_news_posts_featured ON public.news_posts(is_featured);
CREATE INDEX IF NOT EXISTS idx_news_posts_created  ON public.news_posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_posts_views    ON public.news_posts(views_count DESC);
CREATE INDEX IF NOT EXISTS idx_news_posts_tags     ON public.news_posts USING GIN(tags);

-- ============================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================
ALTER TABLE public.profiles          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.students          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tutors            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tutoring_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reviews           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations     ENABLE ROW LEVEL SECURITY;ALTER TABLE public.news_posts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_subscriptions ENABLE ROW LEVEL SECURITY;
-- Drop existing policies if re-running
DROP POLICY IF EXISTS "profiles_select"         ON public.profiles;
DROP POLICY IF EXISTS "profiles_update"         ON public.profiles;
DROP POLICY IF EXISTS "students_select"         ON public.students;
DROP POLICY IF EXISTS "tutors_select"           ON public.tutors;
DROP POLICY IF EXISTS "sessions_select"         ON public.sessions;
DROP POLICY IF EXISTS "messages_select"         ON public.messages;
DROP POLICY IF EXISTS "notifications_select"    ON public.notifications;
DROP POLICY IF EXISTS "notifications_update"    ON public.notifications;
DROP POLICY IF EXISTS "conversations_select"    ON public.conversations;
DROP POLICY IF EXISTS "invoices_select"         ON public.invoices;
DROP POLICY IF EXISTS "assignments_select"      ON public.assignments;
DROP POLICY IF EXISTS "reviews_select"          ON public.reviews;
DROP POLICY IF EXISTS "news_posts_select"       ON public.news_posts;
DROP POLICY IF EXISTS "newsletter_subscriptions_select" ON public.newsletter_subscriptions;
DROP POLICY IF EXISTS "newsletter_subscriptions_insert" ON public.newsletter_subscriptions;

-- Profiles: anyone can read; only owner can update
CREATE POLICY "profiles_select" ON public.profiles
    FOR SELECT USING (TRUE);

CREATE POLICY "profiles_update" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

-- Students: owner or admin
CREATE POLICY "students_select" ON public.students
    FOR SELECT USING (
        profile_id = auth.uid()
        OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- Tutors: approved visible to all; own record always visible; admins see all
CREATE POLICY "tutors_select" ON public.tutors
    FOR SELECT USING (
        status = 'approved'
        OR profile_id = auth.uid()
        OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- Sessions: participants or admin
CREATE POLICY "sessions_select" ON public.sessions
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.students s WHERE s.id = student_id AND s.profile_id = auth.uid())
        OR EXISTS (SELECT 1 FROM public.tutors  t WHERE t.id = tutor_id   AND t.profile_id = auth.uid())
        OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- Messages: conversation participants only
CREATE POLICY "messages_select" ON public.messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.conversations c
            WHERE c.id = conversation_id
            AND (c.participant_a = auth.uid() OR c.participant_b = auth.uid())
        )
    );

-- Conversations: participants or admin
CREATE POLICY "conversations_select" ON public.conversations
    FOR SELECT USING (
        participant_a = auth.uid()
        OR participant_b = auth.uid()
        OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- Notifications: owner only
CREATE POLICY "notifications_select" ON public.notifications
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "notifications_update" ON public.notifications
    FOR UPDATE USING (user_id = auth.uid());

-- Invoices: student owner or admin
CREATE POLICY "invoices_select" ON public.invoices
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.students s WHERE s.id = student_id AND s.profile_id = auth.uid())
        OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- Assignments: student, tutor, or admin
CREATE POLICY "assignments_select" ON public.assignments
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.students s WHERE s.id = student_id AND s.profile_id = auth.uid())
        OR EXISTS (SELECT 1 FROM public.tutors  t WHERE t.id = tutor_id   AND t.profile_id = auth.uid())
        OR EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'admin')
    );

-- Reviews: public
CREATE POLICY "reviews_select" ON public.reviews
    FOR SELECT USING (TRUE);

-- News posts: public read
CREATE POLICY "news_posts_select" ON public.news_posts
    FOR SELECT USING (TRUE);

-- Newsletter subscriptions: anyone can subscribe
CREATE POLICY "newsletter_subscriptions_select" ON public.newsletter_subscriptions
    FOR SELECT USING (TRUE);

CREATE POLICY "newsletter_subscriptions_insert" ON public.newsletter_subscriptions
    FOR INSERT WITH CHECK (TRUE);

-- ============================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_profiles_updated_at  ON public.profiles;
DROP TRIGGER IF EXISTS trg_students_updated_at  ON public.students;
DROP TRIGGER IF EXISTS trg_tutors_updated_at    ON public.tutors;
DROP TRIGGER IF EXISTS trg_sessions_updated_at  ON public.sessions;

CREATE TRIGGER trg_profiles_updated_at  BEFORE UPDATE ON public.profiles  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_students_updated_at  BEFORE UPDATE ON public.students  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_tutors_updated_at    BEFORE UPDATE ON public.tutors    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_sessions_updated_at  BEFORE UPDATE ON public.sessions  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Auto-create profile row when a new user signs up via Supabase Auth
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, full_name, email, role)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
        NEW.email,
        COALESCE((NEW.raw_user_meta_data->>'role')::user_role, 'student')
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Recalculate tutor rating whenever a review is inserted or updated
CREATE OR REPLACE FUNCTION update_tutor_rating()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE public.tutors
    SET
        rating        = (SELECT ROUND(AVG(rating)::NUMERIC, 2) FROM public.reviews WHERE tutor_id = NEW.tutor_id),
        total_reviews = (SELECT COUNT(*)                        FROM public.reviews WHERE tutor_id = NEW.tutor_id)
    WHERE id = NEW.tutor_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_tutor_rating ON public.reviews;
CREATE TRIGGER trg_update_tutor_rating
    AFTER INSERT OR UPDATE ON public.reviews
    FOR EACH ROW EXECUTE FUNCTION update_tutor_rating();

-- Increment tutor total_sessions when a session is marked completed
CREATE OR REPLACE FUNCTION increment_tutor_sessions()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'completed' AND (OLD.status IS NULL OR OLD.status <> 'completed') THEN
        UPDATE public.tutors SET total_sessions = total_sessions + 1 WHERE id = NEW.tutor_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_increment_tutor_sessions ON public.sessions;
CREATE TRIGGER trg_increment_tutor_sessions
    AFTER INSERT OR UPDATE OF status ON public.sessions
    FOR EACH ROW EXECUTE FUNCTION increment_tutor_sessions();

-- ============================================================
-- EXAM SETTINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.exam_settings (
    id                  SERIAL      PRIMARY KEY,
    default_time_minutes INTEGER     DEFAULT 60,
    instructions        TEXT        DEFAULT 'Please read carefully before starting',
    updated_by          UUID        REFERENCES public.profiles(id),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default if not exists
INSERT INTO public.exam_settings (id, default_time_minutes, instructions)
VALUES (1, 60, 'Please read carefully before starting')
ON CONFLICT (id) DO NOTHING;

-- Add tables to realtime publication if not already added
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_rel r
    JOIN pg_class c ON r.prrelid = c.oid
    JOIN pg_publication p ON r.prpubid = p.oid
    WHERE p.pubname = 'supabase_realtime' AND c.relname = 'messages'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_rel r
    JOIN pg_class c ON r.prrelid = c.oid
    JOIN pg_publication p ON r.prpubid = p.oid
    WHERE p.pubname = 'supabase_realtime' AND c.relname = 'notifications'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.notifications;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_rel r
    JOIN pg_class c ON r.prrelid = c.oid
    JOIN pg_publication p ON r.prpubid = p.oid
    WHERE p.pubname = 'supabase_realtime' AND c.relname = 'conversations'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.conversations;
  END IF;
END;
$$;

-- ============================================================
-- MAJESTIC LAB: Institutions, Tokens, Active Sessions, Whiteboard
-- ============================================================

CREATE TABLE IF NOT EXISTS public.lab_institutions (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT        NOT NULL,
    type        TEXT        NOT NULL DEFAULT 'Secondary School',
    contact     TEXT,
    licenses    INTEGER     NOT NULL DEFAULT 1,
    amount_paid DECIMAL(12,2),
    expires_at  TIMESTAMPTZ,
    created_by  UUID        REFERENCES public.profiles(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.lab_tokens (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    token               UUID        NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
    buyer_name          TEXT        NOT NULL,
    amount_paid         DECIMAL(12,2),
    expires_at          TIMESTAMPTZ NOT NULL,
    institution_id      UUID        REFERENCES public.lab_institutions(id) ON DELETE SET NULL,
    session_id          TEXT,
    device_fingerprint  TEXT,
    is_revoked          BOOLEAN     DEFAULT FALSE,
    created_by          UUID        REFERENCES public.profiles(id),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.lab_active_sessions (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    token               UUID        NOT NULL,
    institution_id      UUID        NOT NULL REFERENCES public.lab_institutions(id) ON DELETE CASCADE,
    device_fingerprint  TEXT        NOT NULL,
    last_ping           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (token, device_fingerprint)
);

CREATE TABLE IF NOT EXISTS public.lab_whiteboard_pages (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  TEXT        NOT NULL,
    page_index  INTEGER     NOT NULL DEFAULT 0,
    json_data   JSONB       NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (session_id, page_index)
);

-- Indexes for lab tables
CREATE INDEX IF NOT EXISTS idx_lab_tokens_token          ON public.lab_tokens(token);
CREATE INDEX IF NOT EXISTS idx_lab_tokens_institution    ON public.lab_tokens(institution_id);
CREATE INDEX IF NOT EXISTS idx_lab_active_institution    ON public.lab_active_sessions(institution_id);
CREATE INDEX IF NOT EXISTS idx_lab_whiteboard_session    ON public.lab_whiteboard_pages(session_id);

-- Cleanup function: remove pings older than 10 minutes (stale sessions)
CREATE OR REPLACE FUNCTION cleanup_stale_lab_sessions()
RETURNS void AS $$
BEGIN
    DELETE FROM public.lab_active_sessions
    WHERE last_ping < NOW() - INTERVAL '10 minutes';
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- TUTORS: Missing columns added by features
-- ============================================================
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS exam_code            TEXT;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS exam_time_minutes    INTEGER DEFAULT 60;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS written_exam_score   INTEGER;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS interview_score      INTEGER;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS rejection_reason     TEXT;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS salary_amount        DECIMAL(10,2);
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS salary_frequency     TEXT DEFAULT 'monthly';
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS payment_method       TEXT;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS payment_details      TEXT;
ALTER TABLE public.tutors ADD COLUMN IF NOT EXISTS category             TEXT DEFAULT 'academic';

-- ============================================================
-- EXAM: Questions and Attempts
-- ============================================================
CREATE TABLE IF NOT EXISTS public.exam_questions (
    id             UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    question       TEXT        NOT NULL,
    type           TEXT        NOT NULL DEFAULT 'multiple_choice',
    options        TEXT[],
    correct_answer TEXT,
    model_answer   TEXT,
    pairs          JSONB,
    marks          INTEGER     NOT NULL DEFAULT 1,
    order_num      INTEGER     DEFAULT 0,
    is_active      BOOLEAN     DEFAULT TRUE,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.exam_attempts (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tutor_id            UUID        NOT NULL REFERENCES public.tutors(id) ON DELETE CASCADE,
    profile_id          UUID        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    status              TEXT        NOT NULL DEFAULT 'in_progress',
    answers             JSONB       DEFAULT '{}',
    ai_feedback         JSONB       DEFAULT '{}',
    score               INTEGER,
    total_marks         INTEGER,
    earned_marks        INTEGER,
    time_limit_minutes  INTEGER     NOT NULL DEFAULT 60,
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    submitted_at        TIMESTAMPTZ,
    auto_submitted      BOOLEAN     DEFAULT FALSE,
    tab_switches        INTEGER     DEFAULT 0,
    fullscreen_exits    INTEGER     DEFAULT 0
);

CREATE TABLE IF NOT EXISTS public.exam_answers (
    id                UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    attempt_id        UUID        NOT NULL REFERENCES public.exam_attempts(id) ON DELETE CASCADE,
    question_id       UUID        NOT NULL REFERENCES public.exam_questions(id) ON DELETE CASCADE,
    answer            TEXT,
    is_correct        BOOLEAN,
    marks_awarded     INTEGER,
    ai_feedback       TEXT,
    ai_confidence     TEXT,
    key_points_hit    TEXT[]      DEFAULT '{}',
    key_points_missed TEXT[]      DEFAULT '{}',
    UNIQUE (attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_exam_attempts_tutor    ON public.exam_attempts(tutor_id);
CREATE INDEX IF NOT EXISTS idx_exam_attempts_profile  ON public.exam_attempts(profile_id);
CREATE INDEX IF NOT EXISTS idx_exam_answers_attempt   ON public.exam_answers(attempt_id);

-- ============================================================
-- FORUM
-- ============================================================
CREATE TABLE IF NOT EXISTS public.forum_posts (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id UUID        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    category   TEXT        NOT NULL DEFAULT 'general',
    title      TEXT        NOT NULL,
    content    TEXT        NOT NULL,
    likes      INTEGER     DEFAULT 0,
    is_pinned  BOOLEAN     DEFAULT FALSE,
    is_approved BOOLEAN    DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.forum_comments (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id    UUID        NOT NULL REFERENCES public.forum_posts(id) ON DELETE CASCADE,
    profile_id UUID        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    content    TEXT        NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.forum_likes (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id    UUID        NOT NULL REFERENCES public.forum_posts(id) ON DELETE CASCADE,
    profile_id UUID        NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    UNIQUE (post_id, profile_id)
);

-- ============================================================
-- PROGRESS / FEEDBACK
-- ============================================================
CREATE TABLE IF NOT EXISTS public.progress_records (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id   UUID        REFERENCES public.sessions(id) ON DELETE SET NULL,
    student_id   UUID        NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    tutor_id     UUID        NOT NULL REFERENCES public.tutors(id)   ON DELETE CASCADE,
    subject      TEXT        NOT NULL,
    marks        INTEGER     CHECK (marks BETWEEN 0 AND 100),
    feedback     TEXT,
    strengths    TEXT,
    improvements TEXT,
    recorded_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PARENT REPORT TOKENS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.report_tokens (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    token      TEXT        NOT NULL UNIQUE DEFAULT encode(gen_random_bytes(24), 'hex'),
    student_id UUID        NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
    created_by UUID        REFERENCES public.profiles(id),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- CONTACT MESSAGES
-- ============================================================
CREATE TABLE IF NOT EXISTS public.contact_messages (
    id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name  TEXT        NOT NULL,
    email      TEXT        NOT NULL,
    subject    TEXT        NOT NULL,
    message    TEXT        NOT NULL,
    is_read    BOOLEAN     DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PLATFORM SETTINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.platform_settings (
    id              SERIAL  PRIMARY KEY,
    is_recruiting   BOOLEAN DEFAULT TRUE,
    quiz_enabled    BOOLEAN DEFAULT TRUE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
INSERT INTO public.platform_settings (id, is_recruiting, quiz_enabled)
VALUES (1, TRUE, TRUE)
ON CONFLICT (id) DO NOTHING;

-- TUTOR DOCUMENTS
CREATE TABLE IF NOT EXISTS public.tutor_documents (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tutor_id    UUID        NOT NULL REFERENCES public.tutors(id) ON DELETE CASCADE,
    file_type   TEXT        NOT NULL,
    file_name   TEXT        NOT NULL,
    file_url    TEXT        NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);
