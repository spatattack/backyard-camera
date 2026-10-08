import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'device'))
from motion import Detector, Planner
from camera import Queue
from watch import VideoSource, run

class MotionTests(unittest.TestCase):
    def test_requires_sustained_movement(self):
        d=Detector({'warmup_seconds':0})
        blank=np.zeros((100,100),np.uint8)
        self.assertFalse(d.update(blank,0)[0])
        for i in range(1,4):
            frame=blank.copy();frame[20:50, i*10:i*10+20]=200
            self.assertEqual(d.update(frame,i)[0], i==3)
    def test_ignores_global_light_and_noise(self):
        d=Detector({'warmup_seconds':0,'consecutive_frames':1})
        d.update(np.zeros((50,50)),0)
        self.assertFalse(d.update(np.ones((50,50))*100,1)[0])
        self.assertFalse(d.update(np.ones((50,50))*103,2)[0])
    def test_mask_and_warmup(self):
        d=Detector({'ignore_regions':[[0,0,.5,1]],'consecutive_frames':1,'warmup_seconds':3})
        f=np.zeros((100,100));d.update(f,0)
        f[:,:50]=255;self.assertFalse(d.update(f,4)[0])
        d=Detector({'consecutive_frames':1,'warmup_seconds':3});d.update(np.zeros((100,100)),0)
        self.assertFalse(d.update(f,1)[0])
    def test_burst_cooldown_and_baseline(self):
        p=Planner({},interval=5)
        self.assertEqual(p.update(0,False,0)['trigger'],'scheduled')
        burst=[p.update(t,True,.1) for t in (1,2,3)]
        self.assertEqual(len({x['event_id'] for x in burst}),1)
        self.assertTrue(all(x['trigger']=='motion' for x in burst))
        self.assertIsNone(p.update(4,True,.1))
        self.assertEqual(p.update(5,True,.1)['trigger'],'scheduled')
        self.assertEqual(p.update(31,True,.1)['trigger'],'motion')
    def test_upgrade_preserves_old_queue(self):
        with tempfile.TemporaryDirectory() as root:
            db=sqlite3.connect(Path(root)/'queue.sqlite3')
            db.execute('create table captures(id text primary key,captured_at text,sha256 text,bytes integer,mock integer,jpeg blob)')
            db.execute("insert into captures values ('old','2026-10-08','hash',4,1,?)",(b'\xff\xd8\xff\xd9',));db.commit();db.close()
            q=Queue(root);self.assertEqual(q.first()['id'],'old');self.assertEqual(q.first()['trigger'],'scheduled');q.db.close()
    def test_recorded_video_to_durable_queue(self):
        import cv2
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'clip.avi'
            writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),10,(320,180))
            self.assertTrue(writer.isOpened())
            for i in range(100):
                frame=np.zeros((180,320,3),np.uint8)
                if 35<=i<80:
                    x=20+(i-35)*4;frame[40:140,x:x+40]=255
                writer.write(frame)
            writer.release()
            config={'queue_dir':str(Path(root)/'queue'),'interval_seconds':300}
            count=run(VideoSource(path,5),config,threading.Event(),True)
            q=Queue(config['queue_dir'])
            rows=q.db.execute('select trigger,event_id,mock from captures').fetchall();q.db.close()
            self.assertEqual(count,4)
            self.assertEqual(sum(r[0]=='motion' for r in rows),3)
            self.assertEqual(len({r[1] for r in rows if r[1]}),1)
            self.assertTrue(all(r[2] for r in rows))

if __name__=='__main__': unittest.main()
