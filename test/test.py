"""
최소 기능 테스트 - 핵심 로직만 빠르게 확인

의존성: 표준 라이브러리만 사용 (pandas는 선택적)
실행 시간: ~1초
목적: 핵심 로직이 정상 작동하는지 빠르게 확인
"""

import hashlib
from typing import Any, Dict, List, Tuple

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def normalize_id(id_value: str, hash_it: bool = True) -> str:
    """
    ID 정규화 (핵심 로직)
    
    Args:
        id_value: 정규화할 ID 값
        hash_it: SHA-256 해싱 여부
    
    Returns:
        정규화된 ID 값
    """
    # 소문자 변환
    normalized = id_value.lower()
    
    # 공백 제거
    normalized = normalized.strip()
    
    # 특수문자 제거 (알파벳과 숫자만)
    normalized = ''.join(c for c in normalized if c.isalnum())
    
    # 해싱
    if hash_it:
        normalized = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    return normalized


def compute_intersection(ids_a: List[str], ids_b: List[str]) -> List[str]:
    """
    교집합 계산 (핵심 로직)
    
    Args:
        ids_a: 첫 번째 ID 리스트
        ids_b: 두 번째 ID 리스트
    
    Returns:
        교집합 ID 리스트
    """
    set_a = set(ids_a)
    set_b = set(ids_b)
    return sorted(list(set_a & set_b))  # 정렬하여 일관성 유지


def filter_by_ids(
    data: List[Dict[str, Any]],
    ids: List[str],
    id_key: str
) -> List[Dict[str, Any]]:
    """
    데이터 필터링 (핵심 로직)
    교집합 ID에 해당하는 데이터만 반환
    
    Args:
        data: 필터링할 데이터 리스트
        ids: 필터링할 ID 리스트
        id_key: ID를 나타내는 키
    
    Returns:
        필터링된 데이터 리스트
    """
    id_set = set(ids)
    return [row for row in data if row.get(id_key) in id_set]


def cross_join(
    data_a: List[Dict[str, Any]],
    data_b: List[Dict[str, Any]],
    prefix_a: str = "a_",
    prefix_b: str = "b_"
) -> List[Dict[str, Any]]:
    """
    Cross Join (핵심 로직)
    두 데이터셋의 모든 조합을 생성
    
    Args:
        data_a: 첫 번째 데이터 리스트
        data_b: 두 번째 데이터 리스트
        prefix_a: 첫 번째 데이터의 키에 붙일 접두사
        prefix_b: 두 번째 데이터의 키에 붙일 접두사
    
    Returns:
        모든 조합의 데이터 리스트
    """
    result = []
    for row_a in data_a:
        for row_b in data_b:
            combined = {}
            # 첫 번째 데이터의 키에 접두사 추가
            for key, value in row_a.items():
                combined[f"{prefix_a}{key}"] = value
            # 두 번째 데이터의 키에 접두사 추가
            for key, value in row_b.items():
                combined[f"{prefix_b}{key}"] = value
            result.append(combined)
    return result


def vertical_merge(
    data_a: List[Dict[str, Any]],
    data_b: List[Dict[str, Any]],
    ensure_same_keys: bool = True
) -> List[Dict[str, Any]]:
    """
    Vertical Merge (핵심 로직)
    두 데이터셋을 위아래로 합치기 (행 추가)
    
    Args:
        data_a: 첫 번째 데이터 리스트
        data_b: 두 번째 데이터 리스트
        ensure_same_keys: 모든 행이 동일한 키를 가져야 하는지 여부
    
    Returns:
        합쳐진 데이터 리스트
    """
    if not data_a and not data_b:
        return []
    
    if ensure_same_keys:
        # 모든 키가 동일한지 확인
        if data_a and data_b:
            keys_a = set(data_a[0].keys())
            keys_b = set(data_b[0].keys())
            if keys_a != keys_b:
                raise ValueError(
                    f"Key mismatch: data_a has {keys_a}, data_b has {keys_b}. "
                    "Set ensure_same_keys=False to allow different keys."
                )
    
    # 단순히 두 리스트를 합치기
    return data_a + data_b


def horizontal_merge(
    data_a: List[Dict[str, Any]],
    data_b: List[Dict[str, Any]],
    id_key: str,
    how: str = "inner"
) -> List[Dict[str, Any]]:
    """
    Horizontal Merge (핵심 로직)
    두 데이터셋을 좌우로 합치기 (공통 ID 기준)
    
    Args:
        data_a: 첫 번째 데이터 리스트
        data_b: 두 번째 데이터 리스트
        id_key: 공통 ID 키
        how: 병합 방법 ('inner', 'left', 'right', 'outer')
    
    Returns:
        병합된 데이터 리스트
    """
    if how not in ["inner", "left", "right", "outer"]:
        raise ValueError(f"Invalid 'how' parameter: {how}. Must be one of: inner, left, right, outer")
    
    # data_b를 ID를 키로 하는 딕셔너리로 변환
    dict_b = {row[id_key]: row for row in data_b if id_key in row}
    
    result = []
    
    if how == "inner":
        # 양쪽 모두에 있는 ID만
        for row_a in data_a:
            if id_key in row_a and row_a[id_key] in dict_b:
                merged = {**row_a, **dict_b[row_a[id_key]]}
                # ID 키는 하나만 유지
                if id_key in merged:
                    merged[id_key] = row_a[id_key]
                result.append(merged)
    
    elif how == "left":
        # data_a의 모든 ID (data_b에 없으면 None으로 채움)
        for row_a in data_a:
            if id_key in row_a:
                if row_a[id_key] in dict_b:
                    merged = {**row_a, **dict_b[row_a[id_key]]}
                    merged[id_key] = row_a[id_key]
                else:
                    merged = row_a.copy()
                result.append(merged)
    
    elif how == "right":
        # data_b의 모든 ID (data_a에 없으면 None으로 채움)
        # data_a를 딕셔너리로 변환
        dict_a = {row[id_key]: row for row in data_a if id_key in row}
        for id_val, row_b in dict_b.items():
            if id_val in dict_a:
                merged = {**dict_a[id_val], **row_b}
                merged[id_key] = id_val
            else:
                merged = row_b.copy()
            result.append(merged)
    
    elif how == "outer":
        # 양쪽 모든 ID
        all_ids = set()
        dict_a = {row[id_key]: row for row in data_a if id_key in row}
        for row in data_a:
            if id_key in row:
                all_ids.add(row[id_key])
        for row in data_b:
            if id_key in row:
                all_ids.add(row[id_key])
        
        for id_val in all_ids:
            merged = {}
            if id_val in dict_a:
                merged.update(dict_a[id_val])
            if id_val in dict_b:
                merged.update(dict_b[id_val])
            merged[id_key] = id_val
            result.append(merged)
    
    return result


def test_minimal_workflow() -> Dict[str, int]:
    """
    최소 워크플로우 테스트 (표준 라이브러리만 사용)
    
    Returns:
        테스트 결과 딕셔너리
    """
    print("=" * 60)
    print("핵심 로직 테스트 (표준 라이브러리)")
    print("=" * 60)
    
    # 1. 샘플 데이터
    print("\n[1] 샘플 데이터 준비")
    institution_a = [
        {"id": "P-001", "name": "Alice", "age": 25},
        {"id": "P-002", "name": "Bob", "age": 30},
        {"id": "P-003", "name": "Charlie", "age": 35},
        {"id": "P-004", "name": "David", "age": 40},
    ]
    
    institution_b = [
        {"id": "P-003", "diagnosis": "A", "cost": 1000},
        {"id": "P-004", "diagnosis": "B", "cost": 2000},
        {"id": "P-005", "diagnosis": "C", "cost": 3000},
        {"id": "P-006", "diagnosis": "D", "cost": 4000},
    ]
    
    print(f"  ✓ Institution A: {len(institution_a)} records")
    print(f"  ✓ Institution B: {len(institution_b)} records")
    
    # 2. ID 정규화
    print("\n[2] ID 정규화")
    ids_a_raw = [row["id"] for row in institution_a]
    ids_b_raw = [row["id"] for row in institution_b]
    
    ids_a_normalized = [normalize_id(id_val) for id_val in ids_a_raw]
    ids_b_normalized = [normalize_id(id_val) for id_val in ids_b_raw]
    
    print(f"  ✓ 정규화된 ID A: {len(ids_a_normalized)}개")
    print(f"    예시: {ids_a_normalized[0][:16]}...")
    print(f"  ✓ 정규화된 ID B: {len(ids_b_normalized)}개")
    print(f"    예시: {ids_b_normalized[0][:16]}...")
    
    # 3. 교집합 계산
    print("\n[3] 교집합 계산")
    common_ids_normalized = compute_intersection(ids_a_normalized, ids_b_normalized)
    print(f"  ✓ 교집합 크기: {len(common_ids_normalized)}")
    
    # 원본 ID로 역매핑 (간단한 방법: 원본 ID로 직접 계산)
    common_ids_raw = compute_intersection(ids_a_raw, ids_b_raw)
    print(f"  ✓ 원본 ID 교집합: {common_ids_raw}")
    
    # 4. 데이터 필터링
    print("\n[4] 데이터 필터링")
    filtered_a = filter_by_ids(institution_a, common_ids_raw, "id")
    filtered_b = filter_by_ids(institution_b, common_ids_raw, "id")
    
    print(f"  ✓ 필터링된 A: {len(filtered_a)} records")
    print(f"  ✓ 필터링된 B: {len(filtered_b)} records")
    
    # 5. 결과 요약
    print("\n[5] 결과 요약")
    print("=" * 60)
    print(f"  Input 개수    - A: {len(institution_a)}, B: {len(institution_b)}")
    print(f"  Matching 개수 - 교집합: {len(common_ids_raw)}")
    print(f"  Final 개수    - A: {len(filtered_a)}, B: {len(filtered_b)}")
    print("=" * 60)
    
    # 상세 결과
    if filtered_a or filtered_b:
        print("\n필터링된 데이터:")
        for record in filtered_a:
            print(f"  A: {record}")
        for record in filtered_b:
            print(f"  B: {record}")
    
    return {
        "input_a": len(institution_a),
        "input_b": len(institution_b),
        "matching": len(common_ids_raw),
        "final_a": len(filtered_a),
        "final_b": len(filtered_b),
    }


def test_data_integration() -> Dict[str, int]:
    """
    데이터 통합 테스트 (Cross, Vertical, Horizontal)
    
    Returns:
        테스트 결과 딕셔너리
    """
    print("\n" + "=" * 60)
    print("데이터 통합 테스트 (Cross, Vertical, Horizontal)")
    print("=" * 60)
    
    # 샘플 데이터
    data_a = [
        {"id": "P-001", "name": "Alice", "age": 25},
        {"id": "P-002", "name": "Bob", "age": 30},
    ]
    
    data_b = [
        {"id": "P-002", "diagnosis": "A", "cost": 1000},
        {"id": "P-003", "diagnosis": "B", "cost": 2000},
    ]
    
    print("\n[1] 샘플 데이터")
    print(f"  ✓ Data A: {len(data_a)} records")
    print(f"  ✓ Data B: {len(data_b)} records")
    
    # Cross Join 테스트
    print("\n[2] Cross Join 테스트")
    cross_result = cross_join(data_a, data_b)
    print(f"  ✓ Cross Join 결과: {len(cross_result)} records")
    print(f"    예상: {len(data_a)} × {len(data_b)} = {len(data_a) * len(data_b)}")
    if cross_result:
        print(f"    예시: {cross_result[0]}")
    
    # Vertical Merge 테스트
    print("\n[3] Vertical Merge 테스트")
    # 동일한 키를 가진 데이터로 테스트
    data_a_v = [
        {"id": "P-001", "value": 10},
        {"id": "P-002", "value": 20},
    ]
    data_b_v = [
        {"id": "P-003", "value": 30},
        {"id": "P-004", "value": 40},
    ]
    vertical_result = vertical_merge(data_a_v, data_b_v)
    print(f"  ✓ Vertical Merge 결과: {len(vertical_result)} records")
    print(f"    예상: {len(data_a_v)} + {len(data_b_v)} = {len(data_a_v) + len(data_b_v)}")
    
    # Horizontal Merge 테스트
    print("\n[4] Horizontal Merge 테스트")
    print("  [4-1] Inner Join")
    inner_result = horizontal_merge(data_a, data_b, "id", "inner")
    print(f"    ✓ Inner Join 결과: {len(inner_result)} records")
    if inner_result:
        print(f"    예시: {inner_result[0]}")
    
    print("  [4-2] Left Join")
    left_result = horizontal_merge(data_a, data_b, "id", "left")
    print(f"    ✓ Left Join 결과: {len(left_result)} records")
    
    print("  [4-3] Right Join")
    right_result = horizontal_merge(data_a, data_b, "id", "right")
    print(f"    ✓ Right Join 결과: {len(right_result)} records")
    
    print("  [4-4] Outer Join")
    outer_result = horizontal_merge(data_a, data_b, "id", "outer")
    print(f"    ✓ Outer Join 결과: {len(outer_result)} records")
    
    # 결과 요약
    print("\n[5] 결과 요약")
    print("=" * 60)
    print(f"  Cross Join:    {len(cross_result)} records")
    print(f"  Vertical Merge: {len(vertical_result)} records")
    print(f"  Inner Join:     {len(inner_result)} records")
    print(f"  Left Join:      {len(left_result)} records")
    print(f"  Right Join:        {len(right_result)} records")
    print(f"  Outer Join:     {len(outer_result)} records")
    print("=" * 60)
    
    return {
        "cross": len(cross_result),
        "vertical": len(vertical_result),
        "inner": len(inner_result),
        "left": len(left_result),
        "right": len(right_result),
        "outer": len(outer_result),
    }


def test_with_pandas() -> Dict[str, int]:
    """
    Pandas를 사용한 테스트 (선택적)
    
    Returns:
        테스트 결과 딕셔너리
    """
    if not HAS_PANDAS:
        print("\n⚠️  Pandas not available. Skipping pandas test.")
        return {}
    
    print("\n" + "=" * 60)
    print("Pandas를 사용한 테스트")
    print("=" * 60)
    
    try:
        # DataFrame 생성
        df_a = pd.DataFrame({
            "id": ["P-001", "P-002", "P-003", "P-004"],
            "name": ["Alice", "Bob", "Charlie", "David"],
            "age": [25, 30, 35, 40],
        })
        
        df_b = pd.DataFrame({
            "id": ["P-003", "P-004", "P-005", "P-006"],
            "diagnosis": ["A", "B", "C", "D"],
            "cost": [1000, 2000, 3000, 4000],
        })
        
        print("\n[1] DataFrame 생성")
        print(f"  ✓ df_a: {len(df_a)} rows, {len(df_a.columns)} columns")
        print(f"  ✓ df_b: {len(df_b)} rows, {len(df_b.columns)} columns")
        
        # ID 정규화
        print("\n[2] ID 정규화")
        df_a["normalized_id"] = df_a["id"].apply(normalize_id)
        df_b["normalized_id"] = df_b["id"].apply(normalize_id)
        print(f"  ✓ 정규화 완료")
        
        # 교집합
        print("\n[3] 교집합 계산")
        common_ids = compute_intersection(
            df_a["normalized_id"].tolist(),
            df_b["normalized_id"].tolist()
        )
        print(f"  ✓ 교집합 크기: {len(common_ids)}")
        
        # 필터링
        print("\n[4] 데이터 필터링 및 병합")
        df_a_filtered = df_a[df_a["normalized_id"].isin(common_ids)]
        df_b_filtered = df_b[df_b["normalized_id"].isin(common_ids)]
        
        # 병합
        df_merged = pd.merge(
            df_a_filtered,
            df_b_filtered,
            on="normalized_id",
            how="inner",
            suffixes=("_a", "_b")
        )
        
        print(f"  ✓ 필터링된 A: {len(df_a_filtered)} rows")
        print(f"  ✓ 필터링된 B: {len(df_b_filtered)} rows")
        print(f"  ✓ 병합 결과: {len(df_merged)} rows")
        
        # 결과 출력
        print("\n[5] 결과 요약")
        print("=" * 60)
        print(f"  Input 개수    - A: {len(df_a)}, B: {len(df_b)}")
        print(f"  Matching 개수 - 교집합: {len(common_ids)}")
        print(f"  Final 개수    - 병합: {len(df_merged)}")
        print("=" * 60)
        
        if len(df_merged) > 0:
            print("\n병합된 데이터:")
            display_cols = ["id_a", "name", "diagnosis", "cost"]
            available_cols = [col for col in display_cols if col in df_merged.columns]
            print(df_merged[available_cols].to_string(index=False))
        
        return {
            "input_a": len(df_a),
            "input_b": len(df_b),
            "matching": len(common_ids),
            "final": len(df_merged),
        }
    
    except Exception as e:
        print(f"\n❌ Pandas 테스트 중 오류 발생: {e}")
        return {}


def test_pandas_data_integration() -> Dict[str, int]:
    """
    Pandas를 사용한 데이터 통합 테스트 (Cross, Vertical, Horizontal)
    
    Returns:
        테스트 결과 딕셔너리
    """
    if not HAS_PANDAS:
        print("\n⚠️  Pandas not available. Skipping pandas data integration test.")
        return {}
    
    print("\n" + "=" * 60)
    print("Pandas 데이터 통합 테스트 (Cross, Vertical, Horizontal)")
    print("=" * 60)
    
    try:
        # 샘플 데이터
        df_a = pd.DataFrame({
            "id": ["P-001", "P-002"],
            "name": ["Alice", "Bob"],
            "age": [25, 30],
        })
        
        df_b = pd.DataFrame({
            "id": ["P-002", "P-003"],
            "diagnosis": ["A", "B"],
            "cost": [1000, 2000],
        })
        
        print("\n[1] 샘플 데이터")
        print(f"  ✓ df_a: {len(df_a)} rows, {len(df_a.columns)} columns")
        print(f"  ✓ df_b: {len(df_b)} rows, {len(df_b.columns)} columns")
        
        # Cross Join 테스트
        print("\n[2] Cross Join 테스트")
        df_cross = pd.merge(df_a, df_b, how="cross", suffixes=("_a", "_b"))
        print(f"  ✓ Cross Join 결과: {len(df_cross)} rows")
        print(f"    예상: {len(df_a)} × {len(df_b)} = {len(df_a) * len(df_b)}")
        
        # Vertical Merge 테스트
        print("\n[3] Vertical Merge 테스트")
        # 동일한 컬럼 구조로 테스트
        df_a_v = pd.DataFrame({
            "id": ["P-001", "P-002"],
            "value": [10, 20],
        })
        df_b_v = pd.DataFrame({
            "id": ["P-003", "P-004"],
            "value": [30, 40],
        })
        df_vertical = pd.concat([df_a_v, df_b_v], ignore_index=True)
        print(f"  ✓ Vertical Merge 결과: {len(df_vertical)} rows")
        print(f"    예상: {len(df_a_v)} + {len(df_b_v)} = {len(df_a_v) + len(df_b_v)}")
        
        # Horizontal Merge 테스트
        print("\n[4] Horizontal Merge 테스트")
        print("  [4-1] Inner Join")
        df_inner = pd.merge(df_a, df_b, on="id", how="inner", suffixes=("_a", "_b"))
        print(f"    ✓ Inner Join 결과: {len(df_inner)} rows")
        
        print("  [4-2] Left Join")
        df_left = pd.merge(df_a, df_b, on="id", how="left", suffixes=("_a", "_b"))
        print(f"    ✓ Left Join 결과: {len(df_left)} rows")
        
        print("  [4-3] Right Join")
        df_right = pd.merge(df_a, df_b, on="id", how="right", suffixes=("_a", "_b"))
        print(f"    ✓ Right Join 결과: {len(df_right)} rows")
        
        print("  [4-4] Outer Join")
        df_outer = pd.merge(df_a, df_b, on="id", how="outer", suffixes=("_a", "_b"))
        print(f"    ✓ Outer Join 결과: {len(df_outer)} rows")
        
        # 결과 요약
        print("\n[5] 결과 요약")
        print("=" * 60)
        print(f"  Cross Join:     {len(df_cross)} rows")
        print(f"  Vertical Merge:  {len(df_vertical)} rows")
        print(f"  Inner Join:      {len(df_inner)} rows")
        print(f"  Left Join:       {len(df_left)} rows")
        print(f"  Right Join:      {len(df_right)} rows")
        print(f"  Outer Join:      {len(df_outer)} rows")
        print("=" * 60)
        
        return {
            "cross": len(df_cross),
            "vertical": len(df_vertical),
            "inner": len(df_inner),
            "left": len(df_left),
            "right": len(df_right),
            "outer": len(df_outer),
        }
    
    except Exception as e:
        print(f"\n❌ Pandas 데이터 통합 테스트 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {}


def main() -> int:
    """메인 함수"""
    try:
        # 기본 테스트 (표준 라이브러리만)
        result1 = test_minimal_workflow()
        
        # 데이터 통합 테스트 (표준 라이브러리만)
        result2 = test_data_integration()
        
        # Pandas 테스트 (선택적)
        result3 = test_with_pandas()
        
        # Pandas 데이터 통합 테스트 (선택적)
        result4 = test_pandas_data_integration()
        
        # 최종 요약
        print("\n" + "=" * 60)
        print("✅ 핵심 로직 테스트 완료!")
        print("=" * 60)
        
        if result1:
            print(f"\n[표준 라이브러리] 기본 워크플로우:")
            print(f"  - Input: A={result1['input_a']}, B={result1['input_b']}")
            print(f"  - Matching: {result1['matching']}")
            print(f"  - Final: A={result1['final_a']}, B={result1['final_b']}")
        
        if result2:
            print(f"\n[표준 라이브러리] 데이터 통합:")
            print(f"  - Cross Join: {result2['cross']}")
            print(f"  - Vertical Merge: {result2['vertical']}")
            print(f"  - Inner Join: {result2['inner']}")
            print(f"  - Left Join: {result2['left']}")
            print(f"  - Right Join: {result2['right']}")
            print(f"  - Outer Join: {result2['outer']}")
        
        if result3:
            print(f"\n[Pandas] 기본 워크플로우:")
            print(f"  - Input: A={result3['input_a']}, B={result3['input_b']}")
            print(f"  - Matching: {result3['matching']}")
            print(f"  - Final: {result3['final']}")
        
        if result4:
            print(f"\n[Pandas] 데이터 통합:")
            print(f"  - Cross Join: {result4['cross']}")
            print(f"  - Vertical Merge: {result4['vertical']}")
            print(f"  - Inner Join: {result4['inner']}")
            print(f"  - Left Join: {result4['left']}")
            print(f"  - Right Join: {result4['right']}")
            print(f"  - Outer Join: {result4['outer']}")
        
        return 0
    
    except Exception as e:
        print(f"\n❌ 테스트 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())

