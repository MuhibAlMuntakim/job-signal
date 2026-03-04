import pytest
from unittest.mock import MagicMock, patch
from jobsignal.resume.parser import extract_text_from_pdf, parse_resume_with_llm

def test_extract_text_from_pdf_mock(tmp_path):
    # Mocking pymupdf.open is complex, so we'll just test that it calls the right methods
    with patch("pymupdf.open") as mock_open:
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Sample Resume Text"
        mock_doc.__iter__.return_value = [mock_page]
        mock_open.return_value = mock_doc
        
        result = extract_text_from_pdf("dummy.pdf")
        assert result == "Sample Resume Text"
        mock_open.assert_called_once_with("dummy.pdf")

def test_parse_resume_with_llm_mock():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"full_name": "John Doe", "skills": ["Python", "AI"]}'
    
    with patch("jobsignal.resume.parser.Groq") as mock_groq:
        mock_client = mock_groq.return_value
        mock_client.chat.completions.create.return_value = mock_response
        
        # Mock rate limiter to avoid sleeping
        with patch("jobsignal.resume.parser.rate_limiter.wait_if_needed"):
            result = parse_resume_with_llm("raw text")
            
    assert result["full_name"] == "John Doe"
    assert "Python" in result["skills"]
