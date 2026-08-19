from utils.progress_tracker import start_tracking, update_stage, set_counts, get_progress
import json

start_tracking("job1", "Sant Dadu Dayal ke baare mein bataiye")
update_stage("job1", "PLANNING", "Question type: explanatory")
update_stage("job1", "DISCOVERING", "PDF documents mein search kiya")
set_counts("job1", sources=8, documents=1)
update_stage("job1", "SPECIALIST_ANALYSIS", "3 expert passes complete")
update_stage("job1", "COMPLETE", "Final answer taiyar")

print(json.dumps(get_progress("job1"), indent=2, ensure_ascii=False))