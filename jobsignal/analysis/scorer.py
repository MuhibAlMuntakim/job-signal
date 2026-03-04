import json
from typing import List, Optional
from loguru import logger
from groq import Groq
from jobsignal.config.settings import get_settings
from jobsignal.config.rate_limiter import rate_limiter
from jobsignal.database.models import JobPost, CandidateProfile, JobScore
from jobsignal.database.session import get_session

def score_job(job: JobPost, profile: CandidateProfile) -> JobScore:
    """
    Score a single job against the candidate profile.
    
    Factors:
    - Skill Match (0-40 points) — Groq call
    - Remote Match (0-20 points) — pure logic
    - Salary Match (0-20 points) — pure logic
    - Sector Match (0-20 points) — Groq call
    
    Args:
        job: The JobPost object to score.
        profile: The CandidateProfile object to match against.
        
    Returns:
        A JobScore object (not yet saved to DB).
    """
    settings = get_settings()
    client = Groq(api_key=settings.groq_api_key)
    
    # A) Skill Match (0-40 points) — Groq call
    rate_limiter.wait_if_needed()
    skill_system = "You are a job matching assistant. Return only valid JSON."
    skill_user = f"""Score skill match for this candidate.
Candidate skills: {profile.extracted_skills}
Job description: {job.job_description_raw}

Return JSON:
{{
  "match_score": integer 0-40,
  "matched_skills": [list],
  "missing_skills": [list],
  "explanation": string
}}"""
    try:
        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": skill_system},
                {"role": "user", "content": skill_user}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        skill_res = json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error(f"Skill score LLM failed for job {job.id}: {e}")
        skill_res = {"match_score": 0, "matched_skills": [], "missing_skills": [], "explanation": f"Error: {e}"}

    # B) Remote Match (0-20 points) — pure logic
    remote_score = 10  # Default if no info
    cand_rem = profile.preferred_remote.lower()
    job_rem = job.is_remote
    
    # Logic table from prompt (Note: "Remote" preference implies "Remote, global"):
    # - candidate "remote" + is_remote TRUE  → 20 (Strong match for remote/global)
    # - candidate "remote" + is_remote FALSE → 0
    # - candidate "onsite" + is_remote FALSE → 20
    # - candidate "onsite" + is_remote TRUE  → 5
    # - candidate "hybrid"                   → 10
    # - candidate "any"                      → 15
    if cand_rem == "remote":
        remote_score = 20 if job_rem else 0
    elif cand_rem == "onsite":
        remote_score = 20 if not job_rem else 5
    elif cand_rem == "hybrid":
        remote_score = 10
    elif cand_rem == "any":
        remote_score = 15
    
    # C) Salary Match (0-20 points) — pure logic
    salary_score = 10 # Default for no salary data in job
    if job.salary_min is not None and profile.preferred_salary_min is not None:
        if job.salary_min >= profile.preferred_salary_min:
            salary_score = 20
        elif job.salary_max is not None and job.salary_max < profile.preferred_salary_min:
            salary_score = 0
        else:
            # Partial overlap proportional logic
            # Simplification: If min < pref < max, give 15. If both below but max > 0, give 5.
            if job.salary_max is not None and job.salary_max >= profile.preferred_salary_min:
                salary_score = 15
            else:
                salary_score = 5

    # D) Sector Match (0-20 points) — Groq call
    rate_limiter.wait_if_needed()
    sector_system = "You are a job matching assistant. Return only valid JSON."
    sector_user = f"""Score sector match.
Job sector: {job.sector}
Job description snippet: {job.job_description_raw[:200]}
Candidate preferred sectors: {profile.preferred_sectors}

Return JSON:
{{
  "match_score": integer 0-20,
  "explanation": string
}}"""
    try:
        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": sector_system},
                {"role": "user", "content": sector_user}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        sector_res = json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error(f"Sector score LLM failed for job {job.id}: {e}")
        sector_res = {"match_score": 0, "explanation": f"Error: {e}"}

    final_skill_score = float(skill_res.get("match_score", 0))
    final_sector_score = float(sector_res.get("match_score", 0))
    total_score = final_skill_score + float(remote_score) + float(salary_score) + final_sector_score
    
    return JobScore(
        job_post_id=job.id,
        candidate_profile_id=profile.id,
        score_total=total_score,
        score_skill_match=final_skill_score,
        score_remote_match=float(remote_score),
        score_salary_match=float(salary_score),
        score_sector_match=final_sector_score,
        score_breakdown={
            "skill": skill_res,
            "remote": {"score": remote_score, "logic": f"Candidate: {cand_rem}, Job Remote: {job_rem}"},
            "salary": {"score": salary_score, "logic": f"Job Min: {job.salary_min}, Job Max: {job.salary_max}, Candidate Pref: {profile.preferred_salary_min}"},
            "sector": sector_res
        }
    )

def score_all_unscored_jobs(
    profile: CandidateProfile, 
    target_job_ids: Optional[List[str]] = None,
    progress_callback=None
) -> int:
    """
    Batch score unscored jobs.
    
    Args:
        profile: The active CandidateProfile.
        target_job_ids: Optional list of job UUID strings to score.
        progress_callback: A function taking (current, total, title, company).
        
    Returns:
        The total number of jobs successfully scored.
    """
    with get_session() as session:
        # Get unscored jobs
        query = session.query(JobPost).filter(JobPost.is_scored == False)
        
        if target_job_ids:
            query = query.filter(JobPost.id.in_(target_job_ids))
            
        unscored_jobs = query.all()
        
        if not unscored_jobs:
            logger.info("No unscored jobs found.")
            return 0
            
        unscored_count = len(unscored_jobs)
        total_calls = unscored_count * 2
        estimated_minutes = total_calls / 25
        logger.info(
            f"Scoring {unscored_count} jobs requires "
            f"~{total_calls} Groq calls. "
            f"Estimated: {estimated_minutes:.1f} mins"
        )
        
        scored_at_once = 0
        for i, job in enumerate(unscored_jobs):
            try:
                # We need a fresh reference in the current session if we want to update it
                # or just use it as is if session is shared.
                score_obj = score_job(job, profile)
                session.add(score_obj)
                job.is_scored = True
                
                # Commit frequently to save progress during long runs
                session.commit()
                scored_at_once += 1
                
                if progress_callback:
                    progress_callback(
                        current=i + 1,
                        total=unscored_count,
                        job_title=job.job_title,
                        company=job.company_name
                    )
            except Exception as e:
                logger.error(f"Failed to score job {job.id}: {e}")
                session.rollback()
                
        return scored_at_once
