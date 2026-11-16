import fs from "node:fs";
const BASE="https://danbooru.donmai.us";
const USER_AGENT="ArtistAtlas/1.0 (https://github.com/Tera-Dark/artist-atlas)";
const source=JSON.parse(fs.readFileSync("data/candidates.json","utf8"));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const norm=s=>String(s??"").normalize("NFKC").trim().toLowerCase().replace(/[\s.-]+/g,"_");
const tag=s=>String(s??"").normalize("NFKC").trim().replace(/\s+/g,"_");
async function get(url){
 for(let n=0;n<5;n++){
  const r=await fetch(url,{headers:{Accept:"application/json","User-Agent":USER_AGENT}});
  if(r.status===429||r.status>=500){await sleep(Math.min(30000,1500*2**n));continue}
  if(!r.ok)throw Error("HTTP "+r.status);
  return r.json();
 }
 throw Error("Retry budget exhausted");
}
const results=[];
for(const c of source.candidates){
 const q=tag(c.query);
 const row={candidate_id:c.id,source_tag:c.source_tag,query:c.query,status:"not_found",checked_at:new Date().toISOString(),artist_id:null,canonical_name:null,aliases:[],is_banned:false,is_deleted:false,artist_url:null,post_count:0,previews:[],matches:[],error:null};
 try{
  const artists=await get(BASE+"/artists.json?search[any_name_matches]="+encodeURIComponent(q)+"&limit=20");
  const exact=artists.filter(a=>norm(a.name)===norm(q)||(a.other_names||[]).some(x=>norm(x)===norm(q)));
  const activeExact=exact.filter(a=>!a.is_banned&&!a.is_deleted);
  if(activeExact.length===1){
   // Deleted historical aliases can duplicate a current exact match. Keep the
   // unique active Artist; still send multiple active matches to human review.
   const a=activeExact[0]; row.artist_id=a.id;row.canonical_name=a.name;row.aliases=a.other_names||[];row.is_banned=!!a.is_banned;row.is_deleted=!!a.is_deleted;row.artist_url=BASE+"/artists/"+a.id;
   row.status="verified";
   if(row.status==="verified"){
    await sleep(1100);
    const postTags=[...new Set([a.name,c.query].map(tag).filter(Boolean))];
    let posts=[];
    for(let i=0;i<postTags.length;i++){
     if(i>0)await sleep(1100);
     const tagQuery=postTags[i]+" rating:g order:score";
     posts=await get(BASE+"/posts.json?tags="+encodeURIComponent(tagQuery)+"&limit=3&only=id,rating,score,fav_count,preview_file_url,large_file_url,file_url,is_deleted");
     if(posts.length)break;
    }
    row.previews=posts.filter(p=>!p.is_deleted&&p.rating==="g").map(p=>({id:p.id,rating:p.rating,score:p.score,fav_count:p.fav_count,preview_url:p.preview_file_url||p.media_asset?.variants?.find(v=>v.type==="180x180")?.url||null,large_url:p.large_file_url||p.file_url||null,post_url:BASE+"/posts/"+p.id})).filter(p=>p.preview_url||p.large_url).slice(0,3);
    row.post_count=row.previews.length;if(!row.previews.length)row.status="verified_no_previews";
   }
  }else if(!activeExact.length&&exact.length===1){
   const a=exact[0]; row.artist_id=a.id;row.canonical_name=a.name;row.aliases=a.other_names||[];row.is_banned=!!a.is_banned;row.is_deleted=!!a.is_deleted;row.artist_url=BASE+"/artists/"+a.id;row.status="blocked";
  }else{
   row.status=activeExact.length>1||exact.length>1||artists.length?"needs_review":"not_found";
   row.matches=artists.slice(0,8).map(a=>({id:a.id,name:a.name,aliases:a.other_names||[],is_banned:!!a.is_banned,is_deleted:!!a.is_deleted,url:BASE+"/artists/"+a.id}));
  }
 }catch(e){row.status="error";row.error=String(e.message||e)}
 results.push(row);console.log(c.id,row.status,row.artist_id||"");await sleep(1100);
}
const out={version:1,source_updated_at:source.updated_at,checked_at:new Date().toISOString(),source_count:source.candidates.length,results};
fs.writeFileSync("data/verified-artists.json",JSON.stringify(out,null,2)+"\n");
console.log("Finished",results.length,"candidates");
