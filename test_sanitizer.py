"""Test script for query_sanitizer - unit tests only (no browser needed)"""

from utils.query_sanitizer import sanitize_lanfanshu_query

def test_all():
    tests = [
        # (input, expected_description)
        (
            "Fe3+ fluorescent probe turn-off thiophene detection limit Stern-Volmer",
            "Ion normalization + truncation to 5 words"
        ),
        (
            'B(9,12)-vertex engineering o-carborane thiophene fluorophore Fe3+ sensing mechanism',
            "Hyphen handling + ion normalization + truncation"
        ),
        (
            "o-carborane photophysics",
            "Short query preserved"
        ),
        (
            'carborane fluorophore 综述 文献 carborane fluorophore',
            "Chinese filler removal + dedup"
        ),
        (
            "Hg2+ Cu2+ Zn2+ fluorescent chemosensor selectivity interference mechanism design",
            "Multiple ions + truncation"
        ),
        (
            '"exact match query" for novel study',
            "Quote removal + stop word removal"
        ),
        (
            "   ",
            "Empty/whitespace passthrough"
        ),
    ]

    print("=" * 70)
    print("Query Sanitizer Tests")
    print("=" * 70)

    all_passed = True
    for i, (query, desc) in enumerate(tests, 1):
        result = sanitize_lanfanshu_query(query)
        tokens = result.split()
        ok = len(tokens) <= 5 or not query.strip()

        status = "PASS" if ok else "FAIL"
        if not ok:
            all_passed = False

        print(f"\nTest {i}: {desc}")
        print(f"  Input:  {repr(query)}")
        print(f"  Output: {repr(result)} ({len(tokens)} tokens)")
        print(f"  {status}")

    print("\n" + "=" * 70)
    print(f"Result: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print("=" * 70)

if __name__ == "__main__":
    test_all()
