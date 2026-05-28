"""
PulseMetrics — Data Generator
B2B SaaS Revenue Intelligence. Calibrated to OpenView/Bessemer 2024 benchmarks.
Simulates a €65-75M ARR B2B SaaS company (Intercom/Teamwork tier).
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os, random

np.random.seed(42); random.seed(42)
OUT = "/home/claude/pulsemetrics/data"
os.makedirs(OUT, exist_ok=True)

TIERS = {
    "Enterprise": {"mrr_lo":8000,"mrr_hi":35000,"annual_churn":0.04,"nrr":1.08,
                   "cac":28000,"health_base":72,"n":240},
    "Mid-Market": {"mrr_lo":1500,"mrr_hi":8000,"annual_churn":0.08,"nrr":1.02,
                   "cac":9500,"health_base":62,"n":860},
    "SMB":        {"mrr_lo":199,"mrr_hi":1500,"annual_churn":0.18,"nrr":0.95,
                   "cac":2800,"health_base":52,"n":1300},
}
INDUSTRIES = ["Financial Services","Technology","Healthcare","Manufacturing","Retail","Legal"]
REGIONS = ["UK & Ireland","DACH","Nordics","France","Benelux","Southern Europe","CEE","MEA"]
PRODUCTS = ["Core Platform","Analytics Add-on","Integrations Pack",
            "Enterprise Security","AI Assistant","API Access"]
EVENTS  = ["login","dashboard_view","report_export","integration_triggered",
           "api_call","feature_ai_used","bulk_import","support_opened","admin_action","collab"]
COHORT_START = datetime(2020,1,1)
SIM_END      = datetime(2024,12,31)
REP_NAMES = ["Aoife Murphy","Ciarán Kelly","Sinéad Walsh","Declan O'Brien",
             "Niamh Byrne","Seán Fitzgerald","Caoimhe Ryan","Eoin McCarthy",
             "Roisín Sullivan","Padraig Doyle","Aisling Brennan","Conor Quinn",
             "Orla Hennessy","Fergus Nolan","Deirdre Power","Tadhg Lawlor",
             "Siobhán Murray","Brian Costello"]

def rand_date(s,e): return s+timedelta(days=random.randint(0,(e-s).days))
def next_month(d):  return (d.replace(day=28)+timedelta(days=4)).replace(day=1)

def gen_accounts():
    rows=[]; aid=1
    for tier,c in TIERS.items():
        n_prod = {"Enterprise":3,"Mid-Market":2,"SMB":1}[tier]
        for _ in range(c["n"]):
            start = rand_date(COHORT_START,datetime(2023,6,30))
            mrr   = random.randint(c["mrr_lo"],c["mrr_hi"])
            health= int(np.clip(np.random.normal(c["health_base"],15),10,100))
            rows.append({"account_id":aid,
                "tier":tier,"industry":random.choice(INDUSTRIES),
                "region":random.choice(REGIONS),"start_date":start.strftime("%Y-%m-%d"),
                "cohort_quarter":f"{start.year}Q{(start.month-1)//3+1}",
                "initial_mrr":mrr,"n_products":random.randint(1,n_prod+1),
                "health_score":health,"cac_eur":int(c["cac"]*random.uniform(0.8,1.2)),
                "rep_id":random.randint(1,18),
                "employees":random.randint(
                    *{"Enterprise":(500,10000),"Mid-Market":(50,500),"SMB":(5,50)}[tier])})
            aid+=1
    df=pd.DataFrame(rows)
    df.to_csv(f"{OUT}/accounts.csv",index=False)
    print(f"  Accounts: {len(df):,}")
    return df

def gen_subscriptions(accounts):
    rows=[]
    for _,a in accounts.iterrows():
        tier=a["tier"]; c=TIERS[tier]
        start=datetime.strptime(a["start_date"],"%Y-%m-%d")
        mc = 1-(1-c["annual_churn"])**(1/12)
        mrr=float(a["initial_mrr"]); health=float(a["health_score"])
        churned=False; cur=start.replace(day=1); prev_mrr=None
        while cur<=SIM_END and not churned:
            health=float(np.clip(health+np.random.normal(0.1,2.5),5,100))
            hm=2.5 if health<30 else 1.8 if health<45 else 1.2 if health<55 else 0.7 if health>75 else 1.0
            is_churn=random.random()<mc*hm
            exp=round(mrr*random.uniform(0.08,0.25),2) if random.random()<(0.06 if tier=="Enterprise" else 0.04 if tier=="Mid-Market" else 0.02) and not is_churn else 0.0
            con=round(mrr*random.uniform(0.05,0.15),2) if random.random()<(0.03 if health<50 else 0.01) and not is_churn else 0.0
            mrr=max(mrr+exp-con, a["initial_mrr"]*0.5)
            # MRR movement type
            if prev_mrr is None:         mov="New"
            elif is_churn:               mov="Churned"
            elif exp>0:                  mov="Expansion"
            elif con>0:                  mov="Contraction"
            else:                        mov="Flat"
            rows.append({"account_id":a["account_id"],"tier":tier,
                "month":cur.strftime("%Y-%m"),"mrr":round(mrr,2),
                "health_score":round(health,1),"is_churned_this_month":int(is_churn),
                "expansion_mrr":exp,"contraction_mrr":con,
                "months_active":(cur.year-start.year)*12+(cur.month-start.month),
                "mrr_movement":mov})
            prev_mrr=mrr
            if is_churn: churned=True
            cur=next_month(cur)
    df=pd.DataFrame(rows)
    df.to_csv(f"{OUT}/subscriptions.csv",index=False)
    print(f"  Subscriptions: {len(df):,}")
    return df

def gen_events(accounts):
    rows=[]
    base={"Enterprise":80,"Mid-Market":40,"SMB":15}
    for _,a in accounts.iterrows():
        start=datetime.strptime(a["start_date"],"%Y-%m-%d")
        health=float(a["health_score"]); tier=a["tier"]
        nm=min(36,(SIM_END-start).days//30)
        for m in range(nm):
            mo=(start.replace(day=1)+timedelta(days=32*m)).replace(day=1)
            if mo>SIM_END: break
            n=max(1,int(np.random.poisson(base[tier]*max(0.1,health/100))))
            for _ in range(min(n,40)):
                rows.append({"account_id":a["account_id"],"tier":tier,
                    "event_date":(mo+timedelta(days=random.randint(0,27))).strftime("%Y-%m-%d"),
                    "month":mo.strftime("%Y-%m"),
                    "event_type":random.choices(EVENTS,weights=[20,15,10,8,8,6,5,5,5,8])[0]})
            health=float(np.clip(health+np.random.normal(0.1,2.5),5,100))
    df=pd.DataFrame(rows)
    df.to_csv(f"{OUT}/events.csv",index=False)
    print(f"  Events: {len(df):,}")
    return df

def gen_reps(accounts):
    SENIORITY=["Senior AE","AE","Junior AE"]
    QUOTAS={"Senior AE":900000,"AE":650000,"Junior AE":420000}
    rows=[]
    for i in range(1,19):
        sen=random.choices(SENIORITY,weights=[0.35,0.45,0.20])[0]
        rows.append({"rep_id":i,"name":REP_NAMES[i-1],"seniority":sen,
            "region":random.choice(REGIONS),"annual_quota_eur":QUOTAS[sen],
            "ramp_months":{"Senior AE":2,"AE":4,"Junior AE":6}[sen]})
    df=pd.DataFrame(rows)
    ra=(accounts.groupby("rep_id").agg(
        n_accounts=("account_id","count"),
        total_arr=("initial_mrr",lambda x:(x*12).sum())).reset_index())
    df=df.merge(ra,on="rep_id",how="left").fillna(0)
    df["quota_attainment_pct"]=(df["total_arr"]/df["annual_quota_eur"]*100).round(1)
    df.to_csv(f"{OUT}/reps.csv",index=False)
    print(f"  Reps: {len(df)}")
    return df

def gen_support(accounts):
    CATS=["Onboarding","Integration","Billing","Feature Request","Bug","Performance","API","Training"]
    SEV=["Low","Medium","High","Critical"]
    rows=[]
    base={"Enterprise":3,"Mid-Market":1.5,"SMB":0.6}
    for _,a in accounts.iterrows():
        start=datetime.strptime(a["start_date"],"%Y-%m-%d")
        health=float(a["health_score"]); tier=a["tier"]
        nm=min(36,(SIM_END-start).days//30)
        for m in range(nm):
            mo=(start.replace(day=1)+timedelta(days=32*m)).replace(day=1)
            if mo>SIM_END: break
            n=np.random.poisson(base[tier]*max(0.5,(100-health)/60))
            for _ in range(min(int(n),6)):
                rows.append({"account_id":a["account_id"],"tier":tier,
                    "created_date":(mo+timedelta(days=random.randint(0,27))).strftime("%Y-%m-%d"),
                    "month":mo.strftime("%Y-%m"),
                    "category":random.choice(CATS),
                    "severity":random.choices(SEV,weights=[40,35,18,7])[0],
                    "time_to_close_hrs":random.randint(2,96),
                    "csat_score":random.choices([1,2,3,4,5],weights=[5,8,15,35,37])[0]})
            health=float(np.clip(health+np.random.normal(0,2),5,100))
    df=pd.DataFrame(rows)
    df.to_csv(f"{OUT}/support_tickets.csv",index=False)
    print(f"  Support: {len(df):,}")
    return df

if __name__=="__main__":
    print("PulseMetrics — Generating data...\n")
    accounts=gen_accounts()
    subs=gen_subscriptions(accounts)
    events=gen_events(accounts)
    reps=gen_reps(accounts)
    support=gen_support(accounts)
    active=subs[subs["month"]=="2024-12"]
    arr=active["mrr"].sum()*12
    churns_2024=subs[(subs["month"].str.startswith("2024"))&(subs["is_churned_this_month"]==1)]
    print(f"\n── VERIFIED METRICS ──")
    print(f"  ARR (Dec 2024):    €{arr/1e6:.1f}M")
    print(f"  Active accounts:   {len(active):,}")
    print(f"  Avg MRR/account:   €{active['mrr'].mean():,.0f}")
    print(f"  2024 churned:      {len(churns_2024):,}")
    print(f"  Total events:      {len(events):,}")
    print(f"  Total tickets:     {len(support):,}")
    by_tier=active.groupby("tier")["mrr"].agg(["count","mean","sum"])
    by_tier["arr_m"]=(by_tier["sum"]*12/1e6).round(2)
    print(f"\n  By tier:\n{by_tier[['count','arr_m']].to_string()}")
