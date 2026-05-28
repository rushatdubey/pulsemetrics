-- ============================================================
-- PulseMetrics v2 — SaaS Revenue Intelligence SQL
-- PostgreSQL · Window Functions · CTEs · Revenue Waterfall
-- ============================================================


-- ══════════════════════════════════════════════════════════
-- SCHEMA
-- ══════════════════════════════════════════════════════════

CREATE TABLE accounts (
    account_id           INT PRIMARY KEY,
    tier                 VARCHAR(15),
    industry             VARCHAR(40),
    region               VARCHAR(20),
    sales_rep            VARCHAR(50),
    mrr_initial          NUMERIC(10,2),
    cohort_month         CHAR(7),
    health_score         NUMERIC(5,1),
    logins_per_week      SMALLINT,
    features_used        SMALLINT,
    support_tickets_monthly SMALLINT,
    contract_length_months SMALLINT
);

CREATE TABLE subscriptions (
    id              SERIAL PRIMARY KEY,
    account_id      INT REFERENCES accounts(account_id),
    tier            VARCHAR(15),
    industry        VARCHAR(40),
    region          VARCHAR(20),
    sales_rep       VARCHAR(50),
    month           CHAR(7),
    mrr             NUMERIC(10,2),
    mrr_movement    VARCHAR(15),
    expansion_mrr   NUMERIC(10,2),
    contraction_mrr NUMERIC(10,2),
    is_churned      SMALLINT DEFAULT 0,
    health_score    NUMERIC(5,1),
    tenure_months   SMALLINT,
    logins_per_week SMALLINT,
    features_used   SMALLINT,
    support_tickets SMALLINT
);

CREATE INDEX idx_sub_account ON subscriptions(account_id);
CREATE INDEX idx_sub_month   ON subscriptions(month);
CREATE INDEX idx_sub_tier    ON subscriptions(tier, month);
CREATE INDEX idx_sub_churn   ON subscriptions(is_churned, month);


-- ══════════════════════════════════════════════════════════
-- 1. MRR WATERFALL — New / Expansion / Contraction / Churn
-- ══════════════════════════════════════════════════════════

WITH prev AS (
    SELECT account_id, month, mrr,
        LAG(mrr) OVER (PARTITION BY account_id ORDER BY month) AS prev_mrr,
        LAG(is_churned) OVER (PARTITION BY account_id ORDER BY month) AS was_active
    FROM subscriptions
),
movements AS (
    SELECT
        s.month,
        -- New MRR: first month of account
        SUM(CASE WHEN s.tenure_months = 0         THEN s.mrr ELSE 0 END) AS new_mrr,
        -- Expansion: MRR grew >5%
        SUM(s.expansion_mrr)                                              AS expansion_mrr,
        -- Contraction: MRR shrank
        SUM(s.contraction_mrr)                                            AS contraction_mrr,
        -- Churned: account left
        SUM(CASE WHEN s.is_churned = 1            THEN s.mrr ELSE 0 END) AS churned_mrr,
        -- Active MRR
        SUM(CASE WHEN s.is_churned = 0            THEN s.mrr ELSE 0 END) AS active_mrr,
        COUNT(DISTINCT CASE WHEN s.is_churned = 0 THEN s.account_id END) AS active_accounts
    FROM subscriptions s
    GROUP BY s.month
)
SELECT *,
    new_mrr + expansion_mrr - contraction_mrr - churned_mrr  AS net_new_mrr,
    active_mrr * 12                                          AS arr,
    ROUND(active_mrr * 100.0 /
        NULLIF(LAG(active_mrr) OVER (ORDER BY month), 0) - 100, 2)
                                                             AS mom_growth_pct,
    ROUND(AVG(active_mrr) OVER (
        ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 0)                                                    AS rolling_3m_mrr
FROM movements
ORDER BY month;


-- ══════════════════════════════════════════════════════════
-- 2. NET REVENUE RETENTION BY TIER
-- NRR = (Start MRR + Expansion - Contraction - Churn) / Start MRR
-- ══════════════════════════════════════════════════════════

WITH monthly_cohort AS (
    SELECT tier, month,
        SUM(mrr)             FILTER (WHERE is_churned = 0) AS end_mrr,
        SUM(expansion_mrr)                                 AS expansion,
        SUM(contraction_mrr)                               AS contraction,
        SUM(mrr)             FILTER (WHERE is_churned = 1) AS churned_mrr
    FROM subscriptions
    WHERE tenure_months > 0    -- exclude new accounts from NRR base
    GROUP BY tier, month
),
with_lag AS (
    SELECT *,
        LAG(end_mrr) OVER (PARTITION BY tier ORDER BY month) AS start_mrr
    FROM monthly_cohort
)
SELECT tier, month,
    ROUND((end_mrr + expansion - contraction - churned_mrr) /
          NULLIF(start_mrr, 0) * 100, 1)                    AS nrr,
    ROUND((end_mrr - churned_mrr) /
          NULLIF(start_mrr, 0) * 100, 1)                    AS grr,
    ROUND(expansion / NULLIF(start_mrr, 0) * 100, 2)        AS expansion_pct,
    ROUND(churned_mrr / NULLIF(start_mrr, 0) * 100, 2)      AS churn_pct,
    CASE WHEN nrr > 100 THEN 'Net Expansion' ELSE 'Net Contraction' END AS nrr_status
FROM with_lag
ORDER BY tier, month;


-- ══════════════════════════════════════════════════════════
-- 3. COHORT RETENTION — Dollar & Account Retention
-- ══════════════════════════════════════════════════════════

WITH cohort_base AS (
    SELECT account_id,
        MIN(month) AS cohort_month,
        SUM(mrr)   FILTER (WHERE month = MIN(month) OVER (PARTITION BY account_id))
                   AS base_mrr
    FROM subscriptions
    GROUP BY account_id
),
monthly AS (
    SELECT s.account_id, s.month, s.mrr, s.is_churned,
        c.cohort_month,
        -- Month offset from cohort
        (EXTRACT(YEAR FROM s.month::date) - EXTRACT(YEAR FROM c.cohort_month::date))*12 +
        (EXTRACT(MONTH FROM s.month::date) - EXTRACT(MONTH FROM c.cohort_month::date))
                                                             AS offset_months,
        c.base_mrr
    FROM subscriptions s
    JOIN cohort_base c USING(account_id)
)
SELECT cohort_month,
    offset_months,
    COUNT(DISTINCT account_id)                               AS active_accounts,
    COUNT(DISTINCT FIRST_VALUE(account_id) OVER (
        PARTITION BY cohort_month ORDER BY offset_months))  AS base_accounts,
    SUM(mrr)                                                 AS period_mrr,
    SUM(base_mrr)                                            AS base_mrr,
    ROUND(COUNT(DISTINCT account_id) * 100.0 /
        NULLIF(MAX(COUNT(DISTINCT account_id)) OVER (
            PARTITION BY cohort_month), 0), 1)               AS account_retention_pct,
    ROUND(SUM(mrr) * 100.0 /
        NULLIF(SUM(base_mrr), 0), 1)                        AS revenue_retention_pct
FROM monthly
GROUP BY cohort_month, offset_months
ORDER BY cohort_month, offset_months;


-- ══════════════════════════════════════════════════════════
-- 4. CHURN PREDICTION — EARLY WARNING SIGNALS
-- ══════════════════════════════════════════════════════════

-- Accounts showing declining health + usage in last 90 days
WITH health_trend AS (
    SELECT account_id, tier, mrr,
        health_score                                        AS current_health,
        LAG(health_score, 3) OVER (
            PARTITION BY account_id ORDER BY month)         AS health_3m_ago,
        logins_per_week                                     AS current_logins,
        LAG(logins_per_week, 3) OVER (
            PARTITION BY account_id ORDER BY month)         AS logins_3m_ago,
        features_used,
        support_tickets,
        month
    FROM subscriptions
    WHERE is_churned = 0
),
signals AS (
    SELECT *,
        health_3m_ago - current_health                      AS health_decline,
        logins_3m_ago - current_logins                      AS login_decline,
        CASE
            WHEN current_health < 30                        THEN 'Critical'
            WHEN current_health < 45
              OR health_3m_ago - current_health > 15        THEN 'High'
            WHEN current_health < 55
              OR health_3m_ago - current_health > 8         THEN 'Medium'
            ELSE 'Low'
        END                                                 AS risk_level,
        RANK() OVER (PARTITION BY account_id ORDER BY month DESC) AS recency_rank
    FROM health_trend
    WHERE health_3m_ago IS NOT NULL
)
SELECT account_id, tier, mrr * 12 AS arr, current_health,
    health_decline, current_logins, login_decline,
    features_used, support_tickets, risk_level,
    -- Estimated ARR at risk
    CASE risk_level
        WHEN 'Critical' THEN mrr * 12
        WHEN 'High'     THEN mrr * 12 * 0.7
        WHEN 'Medium'   THEN mrr * 12 * 0.3
        ELSE 0
    END                                                     AS arr_at_risk
FROM signals
WHERE recency_rank = 1
  AND risk_level IN ('Critical','High','Medium')
ORDER BY arr_at_risk DESC;


-- ══════════════════════════════════════════════════════════
-- 5. REP PERFORMANCE — Window Functions
-- ══════════════════════════════════════════════════════════

WITH rep_metrics AS (
    SELECT sales_rep, tier,
        COUNT(DISTINCT CASE WHEN is_churned=0 THEN account_id END) AS active_accounts,
        SUM(CASE WHEN is_churned=0 THEN mrr ELSE 0 END) * 12       AS arr_managed,
        ROUND(AVG(CASE WHEN is_churned=0 THEN health_score END), 1) AS avg_health,
        SUM(CASE WHEN is_churned=1 THEN mrr*12 ELSE 0 END)          AS arr_churned,
        COUNT(DISTINCT CASE WHEN health_score<50 THEN account_id END) AS at_risk_accounts
    FROM subscriptions
    WHERE month = '2024-12'
    GROUP BY sales_rep, tier
)
SELECT sales_rep, tier,
    active_accounts, arr_managed,
    ROUND(arr_managed / 1000000.0, 2)                       AS arr_managed_m,
    avg_health, arr_churned, at_risk_accounts,
    RANK()       OVER (ORDER BY arr_managed DESC)            AS arr_rank,
    PERCENT_RANK() OVER (ORDER BY arr_managed)               AS arr_percentile,
    ROUND(arr_churned * 100.0 /
          NULLIF(arr_managed + arr_churned, 0), 1)           AS churn_exposure_pct
FROM rep_metrics
ORDER BY arr_managed DESC;


-- ══════════════════════════════════════════════════════════
-- 6. UNIT ECONOMICS — LTV:CAC & PAYBACK PERIOD
-- ══════════════════════════════════════════════════════════

WITH account_economics AS (
    SELECT account_id, tier,
        AVG(mrr)     AS avg_mrr,
        COUNT(*)     AS tenure_months,
        MAX(is_churned) AS churned
    FROM subscriptions
    GROUP BY account_id, tier
),
with_cac AS (
    SELECT ae.*,
        -- CAC estimated as ARPA × payback months (tier-specific)
        ROUND(avg_mrr * CASE tier
            WHEN 'Enterprise' THEN 18
            WHEN 'Mid-Market' THEN 22
            ELSE 8 END * 0.85, 0)                           AS estimated_cac,
        -- LTV = ARPA × gross margin / monthly churn
        ROUND(avg_mrr * 0.75 / CASE tier
            WHEN 'Enterprise' THEN 0.0017
            WHEN 'Mid-Market' THEN 0.0085
            ELSE 0.022 END, 0)                              AS estimated_ltv
    FROM account_economics ae
)
SELECT tier,
    ROUND(AVG(avg_mrr), 0)                                  AS avg_arpa,
    ROUND(AVG(estimated_cac), 0)                            AS avg_cac,
    ROUND(AVG(estimated_ltv), 0)                            AS avg_ltv,
    ROUND(AVG(estimated_ltv) /
          NULLIF(AVG(estimated_cac), 0), 2)                 AS ltv_cac_ratio,
    ROUND(AVG(estimated_cac) /
          NULLIF(AVG(avg_mrr) * 0.75, 0), 1)               AS payback_months,
    CASE WHEN AVG(estimated_ltv)/NULLIF(AVG(estimated_cac),0) > 3
         THEN 'Healthy (>3×)' ELSE 'Needs Improvement (<3×)'
    END                                                     AS ltv_cac_status
FROM with_cac
GROUP BY tier
ORDER BY avg_arpa DESC;
