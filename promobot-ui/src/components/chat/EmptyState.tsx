'use client';

import React from 'react';
import Image from 'next/image';

export function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center space-y-7 animate-in fade-in duration-500">
      <div className="relative w-16 h-16 flex items-center justify-center mb-2">
        <Image src="/logo.svg" alt="Keshet Logo" fill className="object-contain drop-shadow-md" priority />
      </div>
      
      <div className="space-y-3 max-w-md">
        <h2 className="text-2xl font-semibold text-slate-800">איך אוכל לעזור לך היום?</h2>
        <p className="text-slate-500 leading-relaxed">
          אני כאן כדי לעזור לך לכתוב, לתכנן ולנתח קמפיינים של פרומו.
          אפשר לשאול אותי שאלות או לבקש ממני לכתוב טקסטים.
        </p>
      </div>
    </div>
  );
}
