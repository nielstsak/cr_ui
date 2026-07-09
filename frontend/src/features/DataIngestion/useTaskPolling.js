
import { useState, useEffect, useRef } from 'react';
import { client } from '../../shared/api/client';

export const useTaskPolling = (taskId, options = {}) => {
  const { onComplete, onFailure, intervalMs = 1500 } = options;
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  
  const savedOnComplete = useRef(onComplete);
  const savedOnFailure = useRef(onFailure);

  useEffect(() => {
    savedOnComplete.current = onComplete;
    savedOnFailure.current = onFailure;
  }, [onComplete, onFailure]);

  useEffect(() => {
    if (!taskId) {
      setProgress(0);
      setStatus(null);
      setError(null);
      setResult(null);
      return;
    }

    setStatus('running');
    setProgress(0);
    setResult(null);

    const interval = setInterval(async () => {
      try {
        const data = await client.get(`/api/tasks/${taskId}`);
        setProgress(data.progress);
        setStatus(data.status);
        if (data.result) {
          setResult(data.result);
        }

        if (data.status === 'completed') {
          clearInterval(interval);
          if (savedOnComplete.current) savedOnComplete.current(data.result);
        } else if (data.status === 'failed') {
          clearInterval(interval);
          setError(data.error);
          if (savedOnFailure.current) savedOnFailure.current(data.error);
        }
      } catch (err) {
        clearInterval(interval);
        setStatus('failed');
        setError(err.message);
        if (savedOnFailure.current) savedOnFailure.current(err.message);
      }
    }, intervalMs);

    return () => clearInterval(interval);
  }, [taskId, intervalMs]);

  return { progress, status, error, result };
};