"""벡터 & 하이브리드 검색 로직."""
from typing import List, Dict, Any

from app.config.opensearch_config import MASTER_INDEX
from app.models.search_model import SearchRequest, SearchResponse, SearchResult
from app.models.vector_store import vector_store
from app.models.embedding_model import embedding_model
from app.models.reranker_model import rerank_results


class SearchService:
    async def vector_search(self, request: SearchRequest) -> SearchResponse:
        query_vec = embedding_model.embed_query(request.query)
        results = vector_store.similarity_search(query_vec, index_name=MASTER_INDEX, k=request.top_k)
        return self._to_response(results)
        
    async def keyword_search(self, request: SearchRequest) -> SearchResponse:
        """순수한 BM25 기반 키워드 검색
        
        이 메서드는 BM25 알고리즘만을 사용해 검색하며, 점수는 0~1 범위로 정규화됩니다.
        """
        # BM25 검색 수행
        results = vector_store.bm25_search(request.query, index_name=MASTER_INDEX, k=request.top_k)
        
        # 점수 정규화 - 최대 점수로 나누어 0~1 범위로 조정
        if results:
            max_score = max([result.score for result in results])
            if max_score > 0:
                for result in results:
                    result.score = result.score / max_score
        
        return self._to_response(results)

    async def hybrid_search_native(self, request: SearchRequest) -> SearchResponse:
        """
        OpenSearch 내장 하이브리드 검색 기능을 사용하여 벡터와 BM25 검색을 합체합니다.
        OpenSearch 검색 파이프라인을 통해 가중치와 점수 정규화를 수행합니다.
        """
        print(f"\n\n===== OpenSearch 내장 하이브리드 검색 시작: 쿼리='{request.query}', top_k={request.top_k} =====", flush=True)
        
        try:
            # 쿼리 텍스트에서 임베딩 생성
            query_vec = embedding_model.embed_query(request.query)
            
            # OpenSearch 내장 하이브리드 검색 수행
            results = vector_store.hybrid_search_with_pipeline(
                query_text=request.query,
                query_vector=query_vec,
                index_name=MASTER_INDEX,
                pipeline_name="hybrid-search-pipeline",
                k=request.top_k
            )
            
            print(f"\n* OpenSearch 내장 하이브리드 검색 결과: {len(results)} 개", flush=True)
            for i, doc in enumerate(results[:5]):  # 처음 5개만 출력
                print(f"  - 결과[{i}]: ID={doc.metadata.doc_id}, 점수={doc.score:.4f}, 청크={doc.metadata.chunk_index}", flush=True)
            
            print("===== OpenSearch 내장 하이브리드 검색 완료 =====\n\n", flush=True)
            return self._to_response(results)
            
        except Exception as e:
            import traceback
            print(f"\n* OpenSearch 내장 하이브리드 검색 오류: {str(e)}", flush=True)
            traceback.print_exc()
            print("===== 하이브리드 검색 오류 완료 =====\n\n", flush=True)
            raise
    

        
    async def hybrid_search_reranked(self, request: SearchRequest) -> SearchResponse:
        """벡터 검색과 키워드 검색 결과를 크로스 인코더로 재정렬하는 하이브리드 검색
        
        1. 벡터 검색과 BM25 검색을 수행하여 결과 추출
        2. 결과를 크로스 인코더 모델을 통해 재정렬 (BAAI/bge-reranker-v2-m3 모델 사용)
        3. 재정렬된 결과를 반환
        """
        print(f"\n\n===== 재정렬 하이브리드 검색 시작: 쿼리='{request.query}', top_k={request.top_k} =====", flush=True)
        
        try:
            # 1. 벡터 검색 수행 (재정렬을 위해 더 많은 후보 가져오기)
            expanded_k = max(request.top_k * 3, 30)  # 재정렬을 위해 더 많은 후보 가져오기
            query_vec = embedding_model.embed_query(request.query)
            vector_results = vector_store.similarity_search(query_vec, index_name=MASTER_INDEX, k=expanded_k)
            print(f"\n* 벡터 검색 결과: {len(vector_results)} 개", flush=True)
            for i, doc in enumerate(vector_results[:3]):  # 처음 3개만 출력
                print(f"  - 벡터[{i}]: ID={doc.metadata.doc_id}, 점수={doc.score:.4f}, 청크={doc.metadata.chunk_index}", flush=True)
            
            # 2. BM25 검색 수행
            bm25_results = vector_store.bm25_search(request.query, index_name=MASTER_INDEX, k=expanded_k)
            print(f"\n* BM25 검색 결과: {len(bm25_results)} 개", flush=True)
            for i, doc in enumerate(bm25_results[:3]):  # 처음 3개만 출력
                print(f"  - BM25[{i}]: ID={doc.metadata.doc_id}, 점수={doc.score:.4f}, 청크={doc.metadata.chunk_index}", flush=True)
            
            # 3. 중복 제거하면서 결과 합치기
            combined_docs = []
            doc_ids_chunks = set()  # doc_id + chunk_index 기준으로 중복 체크
            
            # 3.1 벡터 검색 결과 추가
            for doc in vector_results:
                # doc_id와 chunk_index를 함께 사용하여 중복 확인
                doc_key = f"{doc.metadata.doc_id}_{doc.metadata.chunk_index}"
                if doc_key in doc_ids_chunks:
                    continue
                combined_docs.append(doc)
                doc_ids_chunks.add(doc_key)
            
            # 3.2 BM25 검색 결과 추가
            for doc in bm25_results:
                doc_key = f"{doc.metadata.doc_id}_{doc.metadata.chunk_index}"
                if doc_key in doc_ids_chunks:
                    continue
                combined_docs.append(doc)
                doc_ids_chunks.add(doc_key)
            
            print(f"\n* 총 재정렬 대상 문서: {len(combined_docs)} 개", flush=True)
            
            # 4. 결과가 없으면 빈 결과 반환
            if not combined_docs:
                print("* 결과 없음 - 재정렬 스킵", flush=True)
                return self._to_response([])
            
            # 5. 크로스 인코더로 재정렬 수행
            print("* 크로스 인코더 재정렬 수행 중...", flush=True)
            from app.models.reranker_model import rerank_results
            reranked_docs = rerank_results(request.query, combined_docs, request.top_k)
            
            print(f"\n* 최종 재정렬 결과: {len(reranked_docs)} 개", flush=True)
            for i, doc in enumerate(reranked_docs[:5]):  # 처음 5개만 출력
                print(f"  - 결과[{i}]: ID={doc.metadata.doc_id}, 점수={doc.score:.4f}, 청크={doc.metadata.chunk_index}", flush=True)
            
            print("===== 재정렬 하이브리드 검색 완료 =====\n\n", flush=True)
            return self._to_response(reranked_docs)
            
        except Exception as e:
            import traceback
            print(f"\n* 재정렬 하이브리드 검색 오류: {str(e)}", flush=True)
            traceback.print_exc()
            print("===== 재정렬 하이브리드 검색 오류 완료 =====\n\n", flush=True)
            raise

    def _to_response(self, results: List[SearchResult]) -> SearchResponse:
        """SearchResult 객체 리스트를 SearchResponse 객체로 변환
        """
        return SearchResponse(results=results)
