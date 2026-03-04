import pytest
from unittest.mock import MagicMock, patch
from jobsignal.ingestion.keyword_generator import generate_search_keywords
from jobsignal.database.models import CandidateProfile

def test_generate_search_keywords_mapping():
    profile = CandidateProfile(
        full_name="AI Dev",
        extracted_skills=["Python", "LangChain", "RAG"],
        experience_level="mid",
        sectors_of_experience=["Tech"]
    )
    
    with patch("jobsignal.ingestion.keyword_generator.Groq") as mock_groq:
        mock_client = mock_groq.return_value
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"keywords": ["AI Specialist"]}'
        mock_client.chat.completions.create.return_value = mock_response
        
        with patch("jobsignal.ingestion.keyword_generator.rate_limiter.wait_if_needed"):
            keywords = generate_search_keywords(profile)
            
    assert "LLM Engineer" in keywords  # From rule-based (LangChain)
    assert "AI Specialist" in keywords  # From Groq
