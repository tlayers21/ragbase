"use client";

import { useState, useEffect } from "react";
import { DEFAULT_API_URL, DEFAULT_USER_ID } from "@/lib/config";

export function useSettings() {
  const [userId, setUserIdState] = useState(DEFAULT_USER_ID);
  const [apiUrl, setApiUrlState] = useState(DEFAULT_API_URL);

  useEffect(() => {
    setUserIdState(localStorage.getItem("ragbase_user_id") ?? DEFAULT_USER_ID);
    setApiUrlState(localStorage.getItem("ragbase_api_url") ?? DEFAULT_API_URL);
  }, []);

  function setUserId(value: string) {
    localStorage.setItem("ragbase_user_id", value);
    setUserIdState(value);
  }

  function setApiUrl(value: string) {
    localStorage.setItem("ragbase_api_url", value);
    setApiUrlState(value);
  }

  return { userId, setUserId, apiUrl, setApiUrl };
}
