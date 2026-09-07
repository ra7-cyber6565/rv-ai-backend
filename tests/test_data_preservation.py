"""Stored data survives retention pressure; bounded admission replaces eviction."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from utils.data_preservation import preserve_stored_data
from utils.archive_manifest import ArchiveManifest, sha256_file
from utils.archive_retry import ArchiveRetryQueue
from utils.cloud_storage import ArchiveCoordinator, RemoteObject
from utils.storage_quota import cleanup_verified_archives, assert_capacity, StoragePolicy, StorageQuotaError
from utils.research_runtime import RuntimeStore, RuntimeBlocked


class DataPreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        p = patch.dict(os.environ, {"INFINITY_DATA_ROOT": str(self.root), "INFINITY_PRESERVE_STORED_DATA": "true", "CLOUD_ARCHIVE_PROVIDER": "none"})
        p.start(); self.addCleanup(p.stop)

    def test_missing_or_invalid_configuration_never_authorizes_retention_deletion(self):
        for value in (None, "", "TRUE", "typo", "null", "FALSEE"):
            self.assertTrue(preserve_stored_data({} if value is None else {"INFINITY_PRESERVE_STORED_DATA": value}))
        self.assertFalse(preserve_stored_data({"INFINITY_PRESERVE_STORED_DATA": "false"}))

    def test_even_verified_archive_and_explicit_delete_request_keep_stored_bytes(self):
        source = self.root / 'paper.pdf'; source.write_bytes(b'keep this source')
        class Provider:
            name = 'fixture'
            def upload_file(self, local_path, remote_path):
                self.result = RemoteObject(remote_path, Path(local_path).stat().st_size, sha256_file(local_path))
                return self.result
            def stat(self, path):
                return self.result
        manifest = ArchiveManifest(str(self.root / 'manifest.json'))
        coordinator = ArchiveCoordinator(Provider(), manifest, ArchiveRetryQueue(str(self.root / 'retry.json')))
        result = coordinator.archive(str(source), '/paper.pdf', delete_local=True)
        self.assertTrue(result['verified']); self.assertFalse(result['local_deleted'])
        self.assertEqual(cleanup_verified_archives(manifest, target_reclaim_bytes=999)['deleted_count'], 0)
        from storage.cloud_archive import ArchiveService
        service = ArchiveService(Provider(), manifest)
        self.assertFalse(service.delete_local_if_verified(result['archive_id']))
        self.assertEqual(source.read_bytes(), b'keep this source')
        self.assertFalse(manifest.get(result['archive_id']).get('local_deleted', False))

    def test_capacity_rejection_does_not_reclaim_existing_data(self):
        source = self.root / 'data'; source.write_bytes(b'important')
        with self.assertRaises(StorageQuotaError):
            assert_capacity(20, StoragePolicy(10, 0))
        self.assertEqual(source.read_bytes(), b'important')

    def test_expired_checkpoint_remains_available_for_audit(self):
        store = RuntimeStore(self.root / 'runtime.db')
        limits = dict(http=2, input_bytes=500, output_tokens=50, seconds=60)
        store.start('p', 'old', 'f', 'v', limits)
        with store.transaction() as db:
            db.execute('UPDATE runs SET deadline=0')
        store.start('p', 'new', 'f2', 'v', limits)
        with store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 2)
        with self.assertRaises(RuntimeBlocked):
            store.check('p', 'old')  # Retained evidence does not regain execution rights.

    def test_runtime_capacity_blocks_without_eviction(self):
        store = RuntimeStore(self.root / 'runtime.db')
        with store.transaction() as db:
            db.executemany('INSERT INTO runs(project,run,fingerprint,version,deadline,limits) VALUES(?,?,?,?,?,?)',
                           [('p',str(i),'f','v',0,'{}') for i in range(2000)])
        with self.assertRaises(RuntimeBlocked):
            store.start('p','new','f','v',dict(http=1,input_bytes=10,output_tokens=10,seconds=60))
        with store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0],2000)

    def test_job_history_full_remains_readable_after_restart_and_blocks_new_work(self):
        from utils.research_jobs import ResearchJobRunner
        path = str(self.root / 'jobs.json')
        runner = ResearchJobRunner(max_jobs=1, store_path=path)
        try:
            job = runner.submit(project_id='p',question='fixture',mode='DEEP',custom=None,run=lambda **kw:{'answer':'keep result'})
            deadline = time.monotonic()+5
            while runner.get(job.job_id)['status'] not in {'completed','failed'} and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertEqual(runner.get(job.job_id)['status'],'completed')
            with self.assertRaisesRegex(RuntimeError, 'retained'):
                runner.submit(project_id='p',question='second',mode='DEEP',custom=None,run=lambda **kw: self.fail('must not execute'))
        finally:
            runner.close()
        reopened = ResearchJobRunner(max_jobs=1,store_path=path)
        try:
            self.assertEqual(reopened.get(job.job_id,include_result=True)['result']['answer'],'keep result')
        finally:
            reopened.close()

    def test_full_proposal_history_allows_replay_but_rejects_new_observation_atomically(self):
        from utils.improvement_runtime import ImprovementStore
        store = ImprovementStore(RuntimeStore(self.root / 'proposals.db'))
        for index in range(100):
            store.observe('p', str(index), failed=True)
        before = store.inspect('p')
        store.observe('p', '0', failed=True)
        with self.assertRaisesRegex(RuntimeError, 'retained'):
            store.observe('p', 'new', failed=True)
        self.assertEqual(store.inspect('p'), before)
        self.assertEqual(len(store.observe('other', 'new', failed=True)), 1)

    def test_unfinished_reading_files_are_preserved_and_block_additional_copies(self):
        from research_engine.reading_sessions import ReadingSessionStore, ReadingSessionError, build_metadata
        store = ReadingSessionStore(self.root / 'reading')
        source = self.root / 'incoming.pdf'; source.write_bytes(b'new source')
        metadata = build_metadata(filename='incoming.pdf', access_basis='user_owned_copy')
        for name in ('read_crashed.pdf', 'read_partial.pdf.copying'):
            with self.subTest(name=name):
                folder = store._project_dir(name)
                folder.mkdir(parents=True)
                orphan = folder / name; orphan.write_bytes(b'previous unfinished document')
                with self.assertRaisesRegex(ReadingSessionError, 'retained'):
                    store.create(name, source, metadata)
                self.assertEqual(orphan.read_bytes(), b'previous unfinished document')
                self.assertFalse(list(folder.glob('read_*.json')))
        self.assertEqual(source.read_bytes(), b'new source')


if __name__ == '__main__':
    unittest.main()
