import json
import pymupdf
from loguru import logger
from groq import Groq
from jobsignal.config.settings import get_settings
from jobsignal.config.rate_limiter import rate_limiter
from jobsignal.database.models import CandidateProfile
from jobsignal.database.session import get_session

def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract raw text from a PDF file using PyMuPDF.
    
    Args:
        file_path: Path to the PDF file.
        
    Returns:
        The extracted raw text as a string.
    """
    try:
        doc = pymupdf.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()
    except Exception as e:
        logger.error(f"Failed to extract text from PDF {file_path}: {e}")
        raise

def parse_resume_with_llm(raw_text: str) -> dict:
    """
    Use Groq LLM to parse raw resume text into structured JSON.
    
    Args:
        raw_text: The raw text content of the resume.
        
    Returns:
        A dictionary containing structured resume data.
    """
    settings = get_settings()
    client = Groq(api_key=settings.groq_api_key)
    
    system_prompt = "You are a resume parser. Extract structured information from the resume text. Return only valid JSON."
    user_prompt = f"""Parse this resume and return JSON with these exact keys:
{{
  "full_name": string,
  "email": string or null,
  "skills": [list of technical skill strings],
  "experience_years": integer or null,
  "experience_level": "junior"|"mid"|"senior"|"lead",
  "sectors": [list of industry/sector strings],
  "summary": string (2-3 sentence summary)
}}
Resume: {raw_text}"""

    rate_limiter.wait_if_needed()
    try:
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Groq API call failed during resume parsing: {e}")
        raise

def save_candidate_profile(parsed_data: dict, preferences: dict, raw_text: str, file_name: str) -> CandidateProfile:
    """
    Save the candidate profile to the database and deactivate existing ones.
    
    Args:
        parsed_data: Structured data from parse_resume_with_llm.
        preferences: User preferences from the UI.
        raw_text: The raw text extracted from the PDF.
        file_name: The name of the original resume file.
        
    Returns:
        The newly created CandidateProfile object.
    """
    from sqlalchemy import update
    
    with get_session() as session:
        # Deactivate existing profiles
        session.execute(
            update(CandidateProfile).where(CandidateProfile.is_active == True).values(is_active=False)
        )
        
        # Ensure experience_level is one of the allowed values
        exp_level = parsed_data.get("experience_level", "mid").lower()
        if exp_level not in ["junior", "mid", "senior", "lead"]:
            exp_level = "mid"

        new_profile = CandidateProfile(
            full_name=parsed_data.get("full_name", "Unknown Candidate"),
            email=parsed_data.get("email"),
            extracted_skills=parsed_data.get("skills", []),
            experience_years=parsed_data.get("experience_years"),
            experience_level=exp_level,
            sectors_of_experience=parsed_data.get("sectors", []),
            preferred_remote=preferences.get("preferred_remote", "any"),
            preferred_salary_min=preferences.get("preferred_salary_min"),
            preferred_salary_currency=preferences.get("preferred_salary_currency", "USD"),
            preferred_sectors=preferences.get("preferred_sectors", []),
            resume_raw_text=raw_text,
            resume_file_name=file_name,
            is_active=True
        )
        session.add(new_profile)
        session.commit()
        session.refresh(new_profile)
        return new_profile
