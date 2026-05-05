SELECT
    bzr."zjlx",
    bzr."zjhm",
    bzr."xm",
    tdrz."xp"
FROM "sample_schema"."face_persons" bzr
LEFT JOIN "sample_schema"."face_photos" tdrz
    ON bzr."zjhm" = tdrz."gmsfhm"
WHERE bzr."sflg" = 1
  AND bzr."deleteflag" = 0;
