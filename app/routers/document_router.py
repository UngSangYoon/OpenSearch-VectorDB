"""문서 업로드 라우터 (시각화 API 제거)."""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List
from app.services.document_service import DocumentService
from app.models.document_model import UploadResponse, MultiUploadResponse

print("--- Loading document_router.py ---", flush=True)

router = APIRouter()

doc_service = DocumentService()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    index_name: str = Form(..., description="저장할 콜렉션 이름"),
    file: UploadFile = File(..., description="업로드할 PDF 파일")
):
    """PDF를 업로드하고 지정한 인덱스에 저장한다."""
    print(f"--- Received request for /upload. index_name: {index_name}, filename: {file.filename} ---", flush=True)
    try:
        result = await doc_service.process_upload(file, index_name)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-multiple", response_model=MultiUploadResponse)
async def upload_multiple_documents(
    index_name: str = Form(..., description="저장할 콜렉션 이름"),
    files: List[UploadFile] = File(..., description="업로드할 여러 PDF 파일")
):
    """PDF 파일 여러 개를 한 번에 업로드하고 지정한 인덱스에 저장한다."""
    print(f"--- Received request for /upload-multiple. index_name: {index_name}, file count: {len(files)} ---", flush=True)
    try:
        result = await doc_service.process_multiple_uploads(files, index_name)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
