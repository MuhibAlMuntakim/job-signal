import streamlit as st
import pandas as pd
from loguru import logger
import os
import json
import sys

# Add project root to sys.path
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from jobsignal.database.session import get_session
from jobsignal.database.models import CandidateProfile, JobPost, JobScore
from jobsignal.resume.parser import extract_text_from_pdf, parse_resume_with_llm, save_candidate_profile
from jobsignal.analysis.scorer import score_all_unscored_jobs, score_job
from jobsignal.ingestion.keyword_generator import generate_search_keywords
from jobsignal.ingestion.orchestrator import run_ingestion

# Set page config
st.set_page_config(
    layout="wide",
    page_title="JobSignal",
    page_icon="🎯"
)

# Custom CSS for cards and badges
st.markdown("""
<style>
    .job-card {
        background-color: #1A1F2E;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 24px;
        border: 1px solid #2D3446;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .score-badge {
        padding: 6px 14px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .excellent { background-color: #00FFC2; color: #0E1117; }
    .good { background-color: #00D4FF; color: #0E1117; }
    .partial { background-color: #FFD600; color: #0E1117; }
    .weak { background-color: #6C757D; color: #FFFFFF; }
    
    .stProgress > div > div > div > div {
        background-color: #00D4FF;
    }
    
    .skill-tag {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        margin-right: 5px;
        margin-bottom: 5px;
        font-size: 0.8rem;
    }
    .skill-matched { background-color: rgba(0, 255, 194, 0.2); border: 1px solid #00FFC2; color: #00FFC2; }
    .skill-missing { background-color: rgba(255, 75, 75, 0.2); border: 1px solid #FF4B4B; color: #FF4B4B; }
    .skill-general { background-color: rgba(0, 212, 255, 0.2); border: 1px solid #00D4FF; color: #00D4FF; }
</style>
""", unsafe_allow_html=True)

def main():
    st.sidebar.title("🎯 JobSignal")
    page = st.sidebar.radio("Navigation", ["My Profile", "Top Matches", "Market Intelligence"])
    
    # Initialize session state for profile if needed
    with get_session() as session:
        active_profile = session.query(CandidateProfile).filter(CandidateProfile.is_active == True).order_by(CandidateProfile.created_at.desc()).first()
        
    if page == "My Profile":
        show_profile_page(active_profile)
    elif page == "Top Matches":
        show_matches_page(active_profile)
    elif page == "Market Intelligence":
        show_market_intel_page()

def show_profile_page(active_profile):
    st.title("👤 My Profile")
    
    col_main, col_side = st.columns([2, 1])
    
    with col_side:
        st.subheader("Update Resume")
        with st.form("resume_upload_form"):
            uploaded_file = st.file_uploader("Upload PDF Resume", type=["pdf"])
            remote_pref = st.selectbox("Work Preference", ["Remote", "Onsite", "Hybrid", "Any"], index=3)
            min_salary = st.number_input("Min Salary (USD/month)", min_value=0, value=5000, step=500)
            preferred_sectors = st.multiselect("Preferred Sectors", 
                ["AI/ML", "Fintech", "Healthcare", "Education", "SaaS", "E-commerce", "Cybersecurity", "Gaming"], 
                default=["AI/ML", "SaaS"])
            
            submit_button = st.form_submit_button("Parse & Save Profile")
            
        if submit_button and uploaded_file:
            with st.spinner("Analyzing resume with Groq llama-3.3-70b-versatile..."):
                # Save temp file
                temp_dir = os.path.abspath(os.path.join(root_path, "tmp"))
                if not os.path.exists(temp_dir):
                    os.makedirs(temp_dir)
                
                # Use basename to avoid path issues
                safe_filename = os.path.basename(uploaded_file.name)
                temp_path = os.path.join(temp_dir, f"resume_{safe_filename}")
                
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # Debug info in UI (hidden in expander)
                with st.expander("Debug Info"):
                    st.write(f"Temp Dir: {temp_dir}")
                    st.write(f"Temp Path: {temp_path}")
                    st.write(f"Exists: {os.path.exists(temp_path)}")
                
                try:
                    if not os.path.exists(temp_path):
                        raise FileNotFoundError(f"File not found at {temp_path}")
                        
                    raw_text = extract_text_from_pdf(temp_path)
                    parsed_data = parse_resume_with_llm(raw_text)
                    
                    preferences = {
                        "preferred_remote": remote_pref.lower(),
                        "preferred_salary_min": min_salary,
                        "preferred_salary_currency": "USD",
                        "preferred_sectors": preferred_sectors
                    }
                    
                    save_candidate_profile(parsed_data, preferences, raw_text, uploaded_file.name)
                    st.success("Profile saved!")
                    st.rerun()
                except Exception as e:
                    import traceback
                    st.error(f"Error parsing resume: {e}")
                    st.code(traceback.format_exc())
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
        elif submit_button and not uploaded_file:
            st.error("Please select a PDF file.")

    with col_main:
        if active_profile:
            st.markdown(f"""
            <div class="job-card">
                <h2 style='margin-top:0;'>{active_profile.full_name}</h2>
                <p><b>{active_profile.experience_level.upper()}</b> • {active_profile.experience_years or '0'} years experience</p>
                <p>📧 {active_profile.email or 'No email extracted'}</p>
                <hr style='border: 0.5px solid #2D3446; margin: 15px 0;'>
                <p><b>Search Preferences:</b> {active_profile.preferred_remote.capitalize()} | ${active_profile.preferred_salary_min}+ | {', '.join(active_profile.preferred_sectors or [])}</p>
            </div>
            """, unsafe_allow_html=True)
            
            st.subheader("Extracted Skills")
            skills_html = "".join([f'<span class="skill-tag skill-general">{s}</span>' for s in (active_profile.extracted_skills or [])])
            st.markdown(skills_html, unsafe_allow_html=True)
            
            st.subheader("Dynamic Job Search")
            keywords = generate_search_keywords(active_profile)
            st.write("Keywords to be used for search:")
            st.write(", ".join([f"`{k}`" for k in keywords]))
            
            if st.button("🚀 Run Job Search Now", use_container_width=True):
                with st.status("Fetching live jobs from JSearch, Adzuna, and Remotive...", expanded=True) as status:
                    summaries, target_ids = run_ingestion(queries=keywords)
                    st.session_state.target_job_ids = target_ids
                    status.update(label="Ingestion Complete!", state="complete", expanded=False)
                st.success(f"Found new jobs! Head over to 'Top Matches' to see results.")
        else:
            st.info("No active profile. Upload your resume to begin.")

def show_matches_page(active_profile):
    st.title("🎯 Top Matches")
    
    if not active_profile:
        st.warning("Please upload a resume in 'My Profile' first.")
        return
        
    # Get targeting from session state
    target_ids = st.session_state.get("target_job_ids", [])
    
    with get_session() as session:
        # Show global unscored just for info
        global_unscored = session.query(JobPost).filter(JobPost.is_scored == False).count()
        
        # Count actually targeted jobs
        if target_ids:
            targeted_unscored = session.query(JobPost).filter(
                JobPost.id.in_(target_ids),
                JobPost.is_scored == False
            ).count()
        else:
            targeted_unscored = 0
            
    st.sidebar.subheader("Matching Logic")
    if targeted_unscored > 0:
        st.sidebar.info(f"⏱ {targeted_unscored} fresh jobs need scoring. Approx {targeted_unscored * 2 / 25:.1f} mins.")
        if st.sidebar.button("Score New Jobs", use_container_width=True, type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(current, total, job_title, company):
                progress_bar.progress(current / total)
                status_text.text(f"Scoring {current}/{total}: {job_title} at {company}")
            
            score_all_unscored_jobs(active_profile, target_job_ids=target_ids, progress_callback=update_progress)
            st.success("Targeted scoring finished!")
            # Clear target IDs after successful scoring
            st.session_state.target_job_ids = []
            st.rerun()
    elif global_unscored > 0 and not target_ids:
        st.sidebar.warning(f"Note: {global_unscored} other jobs in DB are unscored. Run a search to target fresh ones.")
    else:
        st.sidebar.success("All targeted jobs scored!")

    # Filters
    st.sidebar.subheader("Filters")
    min_score = st.sidebar.slider("Minimum Match Score", 0, 100, 40)
    remote_only = st.sidebar.checkbox("Remote Only")
    
    with get_session() as session:
        query = session.query(JobPost, JobScore).join(JobScore, JobPost.id == JobScore.job_post_id)\
            .filter(JobScore.candidate_profile_id == active_profile.id)\
            .filter(JobScore.score_total >= min_score)
        
        if remote_only:
            query = query.filter(JobPost.is_remote == True)
            
        results = query.order_by(JobScore.score_total.desc()).limit(20).all()
        
    if not results:
        st.info("No scored matches found above the threshold. Try lowering the score slider or fetching new jobs.")
        return
        
    for job, score in results:
        badge_class = "excellent" if score.score_total >= 80 else "good" if score.score_total >= 60 else "partial" if score.score_total >= 40 else "weak"
        badge_text = "EXCELLENT" if score.score_total >= 80 else "GOOD" if score.score_total >= 60 else "PARTIAL" if score.score_total >= 40 else "WEAK"
        
        with st.container():
            st.markdown(f"""
            <div class="job-card">
                <div style="display: flex; justify-content: space-between; align-items: start;">
                    <div>
                        <h3 style='margin:0;'>{job.job_title}</h3>
                        <p style='color: #00D4FF; font-weight: bold; margin-bottom: 8px;'>{job.company_name}</p>
                    </div>
                    <span class="score-badge {badge_class}">{int(score.score_total)}% {badge_text}</span>
                </div>
                <div style='display: flex; gap: 15px; margin-bottom: 12px;'>
                    <span>📍 {job.location or 'Location N/A'}</span>
                    <span>{'🏠 Remote' if job.is_remote else '🏢 Onsite/Hybrid'}</span>
                    <span>💰 {job.salary_min or '---'} - {job.salary_max or '---'} {job.salary_currency or ''}</span>
                </div>
                <hr style='border: 0.5px solid #2D3446; margin: 12px 0;'>
            </div>
            """, unsafe_allow_html=True)
            
            with st.expander("Match Breakdown & Description"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**Skill Match**")
                    match_data = score.score_breakdown.get('skill', {})
                    matched = match_data.get('matched_skills', [])
                    missing = match_data.get('missing_skills', [])
                    
                    m_html = "".join([f'<span class="skill-tag skill-matched">{m}</span>' for m in matched])
                    st.markdown(m_html or "None", unsafe_allow_html=True)
                    
                    st.write("*Missing:*")
                    mis_html = "".join([f'<span class="skill-tag skill-missing">{m}</span>' for m in missing])
                    st.markdown(mis_html or "None", unsafe_allow_html=True)
                
                with col2:
                    st.write("**Logic Matches**")
                    st.write(f"- **Remote:** {score.score_remote_match}/20")
                    st.write(f"- **Salary:** {score.score_salary_match}/20")
                    st.write(f"- **Sector:** {score.score_sector_match}/20")
                    
                st.write("**AI Explanation:**")
                st.write(match_data.get('explanation', "N/A"))
                
                st.divider()
                st.write("**Job Description:**")
                st.text(job.job_description_raw[:1000] + "...")
                
            if st.button("Apply Now", key=f"btn_{job.id}"):
                st.toast("Application tracking coming in Module 7! 🚀", icon="💡")

def show_market_intel_page():
    st.title("📊 Market Intelligence")
    st.info(
        "📈 Module 3 — Coming Soon\n\n"
        "This dashboard will summarize:\n"
        "- Top skills currently in demand for your profile\n"
        "- Real-time salary benchmarks by role and location\n"
        "- Market sentiment and hiring intensity signals"
    )

if __name__ == "__main__":
    main()
