import pytest
from unittest.mock import MagicMock, patch
from jobsignal.analysis.scorer import score_job
from jobsignal.database.models import JobPost, CandidateProfile

def test_score_job_logic():
    profile = CandidateProfile(
        id="p1",
        full_name="Tester",
        extracted_skills=["Python"],
        preferred_remote="remote",
        preferred_salary_min=100000,
        preferred_sectors=["AI"]
    )
    
    job = JobPost(
        id="j1",
        job_title="Python Dev",
        is_remote=True,
        salary_min=120000,
        job_description_raw="Python developer needed for AI."
    )
    
    with patch("jobsignal.analysis.scorer.Groq") as mock_groq:
        mock_client = mock_groq.return_value
        
        # Skill match mock
        mock_skill_resp = MagicMock()
        mock_skill_resp.choices[0].message.content = '{"match_score": 35, "matched_skills": ["Python"]}'
        
        # Sector match mock
        mock_sector_resp = MagicMock()
        mock_sector_resp.choices[0].message.content = '{"match_score": 15, "explanation": "Matches AI preference"}'
        
        mock_client.chat.completions.create.side_effect = [mock_skill_resp, mock_sector_resp]
        
        with patch("jobsignal.analysis.scorer.rate_limiter.wait_if_needed"):
            score = score_job(job, profile)
            
    assert score.score_skill_match == 35
    assert score.score_remote_match == 20  # remote + remote
    assert score.score_salary_match == 20  # 120k > 100k
    assert score.score_sector_match == 15
    assert score.score_total == 35 + 20 + 20 + 15
