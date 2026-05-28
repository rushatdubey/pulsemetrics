"""PulseMetrics Analytics Pipeline v2 — 14 stages"""
import pandas as pd, numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
import os, warnings; warnings.filterwarnings("ignore")

DATA="/home/claude/pulsemetrics/data"; OUT="/home/claude/pulsemetrics/tableau"
os.makedirs(OUT,exist_ok=True)

def load():
    return (pd.read_csv(f"{DATA}/accounts.csv"),
            pd.read_csv(f"{DATA}/subscriptions.csv"),
            pd.read_csv(f"{DATA}/events.csv"),
            pd.read_csv(f"{DATA}/reps.csv"),
            pd.read_csv(f"{DATA}/support_tickets.csv"))

def s1_waterfall(subs):
    s=subs.copy()
    s["prev_mrr"]=s.groupby("account_id")["mrr"].shift(1)
    m=s.groupby("month").agg(
        total_mrr=("mrr","sum"),
        new_mrr=("mrr",lambda x:x[s.loc[x.index,"prev_mrr"].isna()].sum()),
        expansion_mrr=("expansion_mrr","sum"),
        contraction_mrr=("contraction_mrr","sum"),
        churned_mrr=("mrr",lambda x:x[s.loc[x.index,"is_churned_this_month"]==1].sum()),
        active_accounts=("account_id","nunique"),
        churned_accounts=("is_churned_this_month","sum"),
    ).reset_index()
    m["net_new_mrr"]=(m["new_mrr"]+m["expansion_mrr"]-m["contraction_mrr"]-m["churned_mrr"]).round(2)
    m["arr_m"]=(m["total_mrr"]*12/1e6).round(3)
    m["mom_growth_pct"]=(m["total_mrr"].pct_change()*100).round(2)
    m["rolling_3m"]=(m["total_mrr"].rolling(3,min_periods=1).mean()).round(0)
    m["churn_rate_pct"]=(m["churned_accounts"]/m["active_accounts"]*100).round(2)
    m.to_csv(f"{OUT}/01_mrr_waterfall.csv",index=False)
    print(f"  S1: MRR Waterfall — {len(m)} months"); return m

def s2_nrr(subs,accounts):
    mt=subs.groupby(["month","tier"]).agg(
        mrr=("mrr","sum"),expansion=("expansion_mrr","sum"),
        contraction=("contraction_mrr","sum"),accounts=("account_id","nunique"),
        churned_mrr=("mrr",lambda x:x[subs.loc[x.index,"is_churned_this_month"]==1].sum())
    ).reset_index()
    mt["arr_m"]=(mt["mrr"]*12/1e6).round(3)
    nrr_rows=[]
    for year in range(2021,2025):
        for tier in ["Enterprise","Mid-Market","SMB"]:
            base=subs[(subs["month"]==f"{year-1}-12")&(subs["tier"]==tier)]
            curr=subs[(subs["month"]==f"{year}-12")&(subs["tier"]==tier)]
            if len(base)==0: continue
            ba=set(base["account_id"]); ret=curr[curr["account_id"].isin(ba)]
            base_mrr=base["mrr"].sum()
            nrr=round(ret["mrr"].sum()/base_mrr*100,1) if base_mrr>0 else 0
            nrr_rows.append({"year":year,"tier":tier,"nrr_pct":nrr,
                "base_arr_m":round(base_mrr*12/1e6,2),
                "end_arr_m":round(ret["mrr"].sum()*12/1e6,2)})
    mt.to_csv(f"{OUT}/02_arr_by_tier.csv",index=False)
    ndf=pd.DataFrame(nrr_rows); ndf.to_csv(f"{OUT}/02b_nrr.csv",index=False)
    print(f"  S2: ARR/NRR — {len(mt)} + {len(ndf)} rows"); return mt,ndf

def s3_churn(subs,accounts):
    ch=subs[subs["is_churned_this_month"]==1].copy()
    ch=ch.merge(accounts[["account_id","tier","industry","region","health_score"]],on="account_id",how="left")
    ch["year"]=ch["month"].str[:4].astype(int)
    by_seg=ch.groupby(["year","tier"]).agg(
        churned=("account_id","count"),mrr_lost=("mrr","sum"),
        avg_months=("months_active","mean"),avg_health=("health_score","mean")
    ).reset_index()
    by_seg["arr_lost_m"]=(by_seg["mrr_lost"]*12/1e6).round(2)
    hd=pd.cut(ch["health_score"],bins=[0,30,45,60,75,100],
        labels=["0-30","31-45","46-60","61-75","76-100"]).value_counts().reset_index()
    hd.columns=["health_band","churned_n"]; hd["pct"]=(hd["churned_n"]/len(ch)*100).round(1)
    by_seg.to_csv(f"{OUT}/03_churn_segments.csv",index=False)
    hd.to_csv(f"{OUT}/03b_health_at_churn.csv",index=False)
    ch.to_csv(f"{OUT}/03c_churned_list.csv",index=False)
    print(f"  S3: Churn — {len(ch):,} events"); return ch

def s4_cohort(subs,accounts):
    ac=accounts[["account_id","cohort_quarter"]].copy()
    s2=subs[subs["is_churned_this_month"]==0].merge(ac,on="account_id")
    cs=accounts.groupby("cohort_quarter").size().reset_index(name="cohort_size")
    m=s2.groupby(["cohort_quarter","months_active"]).agg(active=("account_id","nunique")).reset_index()
    m=m.merge(cs,on="cohort_quarter")
    m["retention_pct"]=(m["active"]/m["cohort_size"]*100).round(1)
    piv=m[m["months_active"].isin([0,1,3,6,12,18,24,36])].pivot(
        index="cohort_quarter",columns="months_active",values="retention_pct").reset_index()
    piv.columns=["cohort_quarter"]+[f"M{c}" for c in piv.columns[1:]]
    tr=subs[subs["is_churned_this_month"]==0].merge(
        accounts[["account_id","tier"]],on="account_id")
    tier_ret=tr.groupby(["tier","months_active"]).agg(active=("account_id","nunique")).reset_index()
    ts=accounts.groupby("tier").size().reset_index(name="sz")
    tier_ret=tier_ret.merge(ts,on="tier")
    tier_ret["retention_pct"]=(tier_ret["active"]/tier_ret["sz"]*100).round(1)
    m.to_csv(f"{OUT}/04_cohort_retention.csv",index=False)
    piv.to_csv(f"{OUT}/04b_retention_heatmap.csv",index=False)
    tier_ret.to_csv(f"{OUT}/04c_tier_retention.csv",index=False)
    print(f"  S4: Cohort — {len(piv)} cohorts"); return m,tier_ret

def s5_health(subs,events,support,accounts):
    ev_m=events.groupby(["account_id","month"]).size().reset_index(name="events")
    sw={"Low":0,"Medium":1,"High":3,"Critical":6}
    sup2=support.copy(); sup2["sw"]=sup2["severity"].map(sw)
    su_m=support.groupby(["account_id","month"]).agg(
        tickets=("account_id","count"),sev=("sw" if "sw" in support.columns else "csat_score","sum") if "sw" in support.columns else ("csat_score","count"),
        csat=("csat_score","mean")).reset_index()
    # Fix: compute properly
    sup2_m=sup2.groupby(["account_id","month"]).agg(
        tickets=("account_id","count"),sev_total=("sw","sum"),csat=("csat_score","mean")).reset_index()
    lat=subs[subs["month"]=="2024-12"].copy()
    lat=lat.merge(ev_m[ev_m["month"]=="2024-12"],on=["account_id","month"],how="left")
    lat=lat.merge(sup2_m[sup2_m["month"]=="2024-12"],on=["account_id","month"],how="left")
    lat=lat.merge(accounts[["account_id","tier","industry","region","n_products","cac_eur","initial_mrr","rep_id"]],on="account_id",how="left")
    lat["events"]=lat["events"].fillna(0)
    lat["tickets"]=lat["tickets"].fillna(0)
    lat["sev_total"]=lat["sev_total"].fillna(0)
    lat["csat"]=lat["csat"].fillna(4.0)
    ev_n=lat["events"].clip(upper=200)/200*100
    su_n=np.clip(100-lat["sev_total"]*3,0,100)
    cs_n=(lat["csat"]-1)/4*100
    lat["computed_health"]=(lat["health_score"]*0.40+ev_n*0.35+su_n*0.15+cs_n*0.10).clip(5,100).round(1)
    lat["health_tier"]=lat["computed_health"].apply(lambda x:
        "Healthy (>75)" if x>75 else "Moderate (60-75)" if x>60 else
        "At Risk (45-60)" if x>45 else "Critical (<45)")
    lat["churn_risk"]=lat["computed_health"].apply(lambda x:
        "High" if x<45 else "Medium" if x<60 else "Low")
    lat.to_csv(f"{OUT}/05_account_health.csv",index=False)
    print(f"  S5: Health — {len(lat):,} accounts"); return lat

def s6_usage(events,accounts):
    maa=events.groupby("month").agg(
        active_accounts=("account_id","nunique"),total_events=("event_type","count")).reset_index()
    maa["events_per_acct"]=(maa["total_events"]/maa["active_accounts"]).round(1)
    feat=events.groupby(["month","event_type"]).agg(
        accounts=("account_id","nunique"),events=("event_type","count")).reset_index()
    sticky=events.groupby(["account_id","month"])["event_type"].nunique().reset_index(name="types_used")
    sticky["is_sticky"]=sticky["types_used"]>=3
    sr=sticky.groupby("month")["is_sticky"].mean().reset_index(name="stickiness_rate")
    sr["stickiness_pct"]=(sr["stickiness_rate"]*100).round(1)
    tf=events.merge(accounts[["account_id","tier"]],on="account_id")
    tier_feat=tf.groupby(["tier","event_type"]).agg(
        accounts=("account_id","nunique"),events=("event_type","count")).reset_index()
    maa.to_csv(f"{OUT}/06_usage_trend.csv",index=False)
    feat.to_csv(f"{OUT}/06b_feature_adoption.csv",index=False)
    sr.to_csv(f"{OUT}/06c_stickiness.csv",index=False)
    tier_feat.to_csv(f"{OUT}/06d_tier_features.csv",index=False)
    print(f"  S6: Usage — {len(maa)} months"); return maa,feat

def s7_forecast(mw):
    df=mw.copy(); df["dt"]=pd.to_datetime(df["month"])
    avg_g=df.tail(6)["mom_growth_pct"].mean()/100
    last=df.iloc[-1]; mrr_f=last["total_mrr"]; rows=[]
    for i in range(1,7):
        mrr_f*=(1+avg_g)
        fd=last["dt"]+pd.DateOffset(months=i)
        rows.append({"month":fd.strftime("%Y-%m"),"total_mrr":round(mrr_f,0),
            "arr_m":round(mrr_f*12/1e6,3),"is_forecast":True,
            "lower_bound":round(mrr_f*0.94,0),"upper_bound":round(mrr_f*1.06,0)})
    df["is_forecast"]=False
    full=pd.concat([df[["month","total_mrr","arr_m","is_forecast","rolling_3m","mom_growth_pct"]],
        pd.DataFrame(rows)],ignore_index=True)
    full.to_csv(f"{OUT}/07_forecast.csv",index=False)
    print(f"  S7: Forecast — 6-month forward"); return full

def s8_unit_econ(accounts,subs):
    rows=[]
    for tier in ["Enterprise","Mid-Market","SMB"]:
        a=accounts[accounts["tier"]==tier]
        s=subs[subs["tier"]==tier]
        lat=s[s["month"]=="2024-12"]; avg_mrr=lat["mrr"].mean() if len(lat)>0 else 0
        ch=s[s["is_churned_this_month"]==1]; avg_ten=ch["months_active"].mean() if len(ch)>0 else 36
        avg_cac=a["cac_eur"].mean()
        ltv=avg_mrr*avg_ten*0.72
        payback=avg_cac/(avg_mrr*0.72) if avg_mrr>0 else 0
        rows.append({"tier":tier,"accounts":len(a),
            "avg_mrr":round(avg_mrr,0),"avg_arr":round(avg_mrr*12,0),
            "avg_cac":round(avg_cac,0),"avg_tenure_months":round(avg_ten,1),
            "ltv":round(ltv,0),"ltv_cac_ratio":round(ltv/avg_cac,2) if avg_cac>0 else 0,
            "payback_months":round(payback,1),"gross_margin_pct":72.0,
            "magic_number":round((avg_mrr*12*len(a)*0.25)/(avg_cac*len(a)*0.25),2) if avg_cac>0 else 0})
    df=pd.DataFrame(rows); df.to_csv(f"{OUT}/08_unit_economics.csv",index=False)
    print(f"  S8: Unit Economics"); return df

def s9_reps(reps,accounts,subs):
    ra=accounts.groupby("rep_id").agg(
        n_accounts=("account_id","count"),total_arr=("initial_mrr",lambda x:(x*12).sum()),
        avg_size=("initial_mrr","mean")).reset_index()
    ca_ids=subs[subs["is_churned_this_month"]==1]["account_id"].unique()
    ce=accounts[accounts["account_id"].isin(ca_ids)].groupby("rep_id").agg(
        churned_n=("account_id","count"),churned_arr=("initial_mrr",lambda x:(x*12).sum())).reset_index()
    df=reps.merge(ra,on="rep_id",how="left").merge(ce,on="rep_id",how="left").fillna(0)
    df["quota_attainment"]=(df["total_arr"]/df["annual_quota_eur"]*100).round(1)
    df["churn_rate_pct"]=(df["churned_n"]/df["n_accounts"].replace(0,1)*100).round(1)
    df["arr_per_account"]=(df["total_arr"]/df["n_accounts"].replace(0,1)).round(0)
    df["rank"]=df["total_arr"].rank(ascending=False).astype(int)
    df.to_csv(f"{OUT}/09_rep_performance.csv",index=False)
    print(f"  S9: Reps — {len(df)} reps"); return df

def s10_at_risk(health,accounts,subs):
    lat=health.copy()
    trend=subs[subs["month"].isin(["2024-10","2024-11","2024-12"])].groupby("account_id").apply(
        lambda x:x.sort_values("month")["health_score"].diff().mean()).reset_index(name="trend_3m")
    lat=lat.merge(trend,on="account_id",how="left")
    lat["trend_3m"]=lat["trend_3m"].fillna(0)
    lat["at_risk"]=(lat["computed_health"]<60)|(lat["trend_3m"]<-2)|(lat["churn_risk"]=="High")
    ar=lat[lat["at_risk"]].copy()
    ar["arr_at_risk"]=(ar["mrr"]*12).round(0)
    ar["priority"]=ar["arr_at_risk"].apply(lambda x:
        "P1 – Immediate" if x>100000 else "P2 – Urgent" if x>40000 else "P3 – Monitor")
    ar=ar.sort_values("arr_at_risk",ascending=False)
    ar.to_csv(f"{OUT}/10_at_risk.csv",index=False)
    print(f"  S10: At-Risk — {len(ar):,} accounts (€{ar['arr_at_risk'].sum()/1e6:.1f}M)")
    return ar

def s11_support(support,accounts):
    s=support.merge(accounts[["account_id","tier"]],on="account_id",how="left")
    csat=s.groupby(["month","tier"]).agg(
        avg_csat=("csat_score","mean"),tickets=("account_id","count"),
        avg_ttc=("time_to_close_hrs","mean")).reset_index()
    csat["avg_csat"]=csat["avg_csat"].round(2); csat["avg_ttc"]=csat["avg_ttc"].round(1)
    cat=s.groupby(["tier","category"]).agg(
        tickets=("account_id","count"),avg_csat=("csat_score","mean"),
        avg_ttc=("time_to_close_hrs","mean")).reset_index()
    csat.to_csv(f"{OUT}/11_support_csat.csv",index=False)
    cat.to_csv(f"{OUT}/11b_support_categories.csv",index=False)
    print(f"  S11: Support — {len(s):,} tickets"); return csat

def s12_expansion(subs,accounts):
    e=subs[subs["expansion_mrr"]>0].copy()
    e=e.merge(accounts[["account_id","tier","industry"]],on="account_id",how="left")
    me=e.groupby(["month","tier"]).agg(
        n_accounts=("account_id","nunique"),total_exp=("expansion_mrr","sum"),
        avg_exp=("expansion_mrr","mean")).reset_index()
    me["exp_arr_m"]=(me["total_exp"]*12/1e6).round(3)
    bi=e.groupby("industry").agg(
        expansions=("account_id","count"),total_exp=("expansion_mrr","sum"),
        avg_exp=("expansion_mrr","mean")).reset_index().sort_values("total_exp",ascending=False)
    me.to_csv(f"{OUT}/12_expansion.csv",index=False)
    bi.to_csv(f"{OUT}/12b_expansion_by_industry.csv",index=False)
    print(f"  S12: Expansion — {len(e):,} events"); return me

def s13_model(health,subs,events,support,accounts):
    f=health[["account_id","tier","computed_health","events","tickets",
              "csat","mrr","months_active","health_score","n_products"]].copy()
    f=f.rename(columns={"events":"monthly_events","csat":"avg_csat"})
    f=f.merge(accounts[["account_id","initial_mrr"]],on="account_id",how="left")
    ef=(subs[subs["expansion_mrr"]>0]["account_id"].value_counts()
           .reset_index().rename(columns={"count":"n_exp","account_id":"account_id"}))
    # Fix column naming for different pandas versions
    if "account_id" not in ef.columns:
        ef.columns = ["account_id","n_exp"]
    f=f.merge(ef,on="account_id",how="left")
    f["n_exp"]=f["n_exp"].fillna(0)
    f["mrr_growth"]=((f["mrr"]-f["initial_mrr"])/f["initial_mrr"].replace(0,1)).round(3)
    f=f.fillna(f.median(numeric_only=True))
    fc=subs[(subs["month"].isin(["2024-10","2024-11","2024-12"]))&
            (subs["is_churned_this_month"]==1)]["account_id"].unique()
    f["will_churn"]=f["account_id"].isin(fc).astype(int)
    cols=["computed_health","monthly_events","tickets","avg_csat",
          "months_active","n_products","mrr_growth","n_exp"]
    X=f[cols].values; y=f["will_churn"].values
    Xs=StandardScaler().fit_transform(X)
    m=LogisticRegression(max_iter=1000,class_weight="balanced").fit(Xs,y)
    proba=m.predict_proba(Xs)[:,1]
    auc=roc_auc_score(y,proba)
    f["churn_prob"]=proba.round(4)
    f["churn_risk_band"]=pd.cut(proba,bins=[0,0.15,0.30,0.50,1.0],
        labels=["Low","Medium","High","Very High"])
    imp=pd.DataFrame({"feature":cols,"coef":m.coef_[0],
        "abs_imp":np.abs(m.coef_[0])}).sort_values("abs_imp",ascending=False)
    imp["direction"]=imp["coef"].apply(lambda c:"↑ Churn" if c>0 else "↓ Churn")
    f.to_csv(f"{OUT}/13_churn_predictions.csv",index=False)
    imp.to_csv(f"{OUT}/13b_model_features.csv",index=False)
    print(f"  S13: Churn Model — AUC={auc:.3f} | High/VH risk: {(proba>0.30).sum():,}")
    return f,imp,auc

def s14_exec(mw,nrr,ue,ar,auc):
    rows=[]
    for year in range(2021,2025):
        r=mw[mw["month"]==f"{year}-12"]
        if len(r)==0: continue
        r=r.iloc[0]
        ne=nrr[(nrr["year"]==year)&(nrr["tier"]=="Enterprise")]
        nm=nrr[(nrr["year"]==year)&(nrr["tier"]=="Mid-Market")]
        ue_e=ue[ue["tier"]=="Enterprise"].iloc[0]
        rows.append({"year":year,"arr_m":r["arr_m"],
            "active_accounts":r["active_accounts"],
            "monthly_churn_pct":r["churn_rate_pct"],
            "nrr_enterprise":ne["nrr_pct"].values[0] if len(ne) else None,
            "nrr_midmarket":nm["nrr_pct"].values[0] if len(nm) else None,
            "ltv_cac_enterprise":ue_e["ltv_cac_ratio"],
            "payback_months":ue_e["payback_months"],
            "arr_at_risk_m":round(ar["arr_at_risk"].sum()/1e6,2) if year==2024 else None,
            "model_auc":round(auc,3) if year==2024 else None})
    df=pd.DataFrame(rows); df.to_csv(f"{OUT}/14_exec_scorecard.csv",index=False)
    print(f"  S14: Exec Scorecard — {len(df)} years"); return df

if __name__=="__main__":
    print("PulseMetrics Analytics Pipeline v2\n"+"="*45)
    accounts,subs,events,reps,support=load()
    mw=s1_waterfall(subs)
    mt,nrr=s2_nrr(subs,accounts)
    ch=s3_churn(subs,accounts)
    cohort,tr=s4_cohort(subs,accounts)
    health=s5_health(subs,events,support,accounts)
    maa,feat=s6_usage(events,accounts)
    fc=s7_forecast(mw)
    ue=s8_unit_econ(accounts,subs)
    rp=s9_reps(reps,accounts,subs)
    ar=s10_at_risk(health,accounts,subs)
    cs=s11_support(support,accounts)
    ex=s12_expansion(subs,accounts)
    preds,imp,auc=s13_model(health,subs,events,support,accounts)
    exc=s14_exec(mw,nrr,ue,ar,auc)
    print(f"\n✓ All Tableau CSVs written")
    last=mw.iloc[-1]
    print(f"\n── HEADLINE (Dec 2024) ──")
    print(f"  ARR:            €{last['arr_m']:.1f}M")
    print(f"  Monthly Churn:  {last['churn_rate_pct']:.2f}%")
    print(f"  At-Risk ARR:    €{ar['arr_at_risk'].sum()/1e6:.1f}M")
    print(f"  Churn AUC:      {auc:.3f}")
    print(f"\n── NRR (2024) ──")
    print(nrr[nrr["year"]==2024][["tier","nrr_pct"]].to_string(index=False))
    print(f"\n── UNIT ECONOMICS ──")
    print(ue[["tier","ltv_cac_ratio","payback_months"]].to_string(index=False))
