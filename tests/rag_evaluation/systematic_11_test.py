import requests
import time
import subprocess
import json

BASE_URL = "http://localhost:8000"

# List of test files to upload and their specific verification queries
test_scenarios = [
    ("tscript1.txt", "Meeting discussion?", "1.8 million"),
    ("tscript2_technical.txt", "Meeting discussion?", "512Mi"),
    ("tscript3_conflict.txt", "What was the conflict about?", "fiscal policy"),
    ("tscript7_legal.txt", "What are the IP indemnification terms?", "indemnification"),
    ("tscript4_informal.txt", "What about the coffee machine?", "coffee"),
    ("tscript5_fragmented.txt", "What was the video conference connection issue?", "video"),
    ("tscript6_casual.txt", "What team building event was discussed?", "escape room"),
    ("tscript8_brainstorm.txt", "What are the wild ideas?", "AI"),
    ("tscript9_sales.txt", "Who is the lead prospect?", "TechDynamics"),
    ("tscript10_board.txt", "What is the strategic pivot?", "Enterprise"),
    ("testFailureMeeting.txt", "What caused the failure?", "database")
]

def get_db_doc_count():
    """Get current document count from LanceDB via docker"""
    try:
        result = subprocess.run(
            ['docker', 'exec', 'meeting_intelligence_system-api-1', 'python', '-c',
             "import lancedb; db = lancedb.connect('data/lancedb'); tbl = db.open_table('meeting_segments'); print(len(tbl))"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return int(result.stdout.strip())
    except:
        return -1

def test_query(specific_query):
    """Test if queries work"""
    try:
        response = requests.post(
            f"{BASE_URL}/api/query",
            json={"query": specific_query},
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            answer = data.get('answer', '')
            sources = len(data.get('sources', []))
            return True, sources, answer
        else:
            return False, 0, f"Status {response.status_code}: {response.text}"
    except Exception as e:
        return False, 0, str(e)

print("=" * 70)
print("SYSTEMATIC 11-DOCUMENT UPLOAD TEST (Specific Questions)")
print("=" * 70)
print()

total_uploaded = 0

for i, (filename, query_text, expected_keyword) in enumerate(test_scenarios, 1):
    print(f"[{i}/11] Uploading {filename}...")
    
    # Upload
    try:
        with open(f"meeting_transcripts_sample/{filename}", 'rb') as f:
            response = requests.post(
                f"{BASE_URL}/api/upload",
                files={'file': f},
                timeout=30
            )
        
        if response.status_code == 200:
            data = response.json()
            segments = data.get('segments_count', 0)
            print(f"       ✓ Upload OK ({segments} segments)")
            total_uploaded += 1
        else:
            print(f"       ✗ Upload failed ({response.status_code})")
    except Exception as e:
        print(f"       ✗ Error: {e}")
        continue
    
    # Check DB count
    time.sleep(1) # Give it a second to persist
    db_count = get_db_doc_count()
    print(f"       DB total: {db_count} docs")
    
    # Check query
    print(f"       Q: \"{query_text}\"")
    works, sources, output = test_query(query_text)
    if works:
        preview = output[:100].replace('\n', ' ')
        print(f"       ✓ Query OK ({sources} sources)")
        print(f"       A: {preview}...")
        
        # Simple keyword check
        if expected_keyword.lower() in output.lower():
             print(f"       ✅ Verified content (found '{expected_keyword}')")
        else:
             print(f"       ⚠️ Content mismatch? (Did not find '{expected_keyword}')")
             
    else:
        print(f"       ✗ Query FAILED")
        print(f"       Error: {output}")
    
    print()

print("=" * 70)
print("FINAL STATE")
print("=" * 70)
final_db_count = get_db_doc_count()
print(f"Successfully uploaded: {total_uploaded}/{len(test_files)}")
print(f"DB contains: {final_db_count} total documents")
