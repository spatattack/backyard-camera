'use client';

import {useRouter} from 'next/navigation';
import {useEffect} from 'react';
import {startArchiveRefresh} from '../lib/archive-refresh';

export default function ArchiveRefresh() {
  const router = useRouter();
  useEffect(() => startArchiveRefresh(() => router.refresh()), [router]);
  return null;
}
