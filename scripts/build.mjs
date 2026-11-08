import fs from 'node:fs';
import path from 'node:path';
const root=process.cwd();const out=path.join(root,'dist');
const read=p=>JSON.parse(fs.readFileSync(path.join(root,p),'utf8'));
// Pages CMS writes /media/... URLs. Remove the leading slash so project Pages URLs also work.
function media(value){if(!value)return '';if(typeof value!=='string')throw Error('画像のパスは文字列で指定してください。');const p=value.replace(/^\/+/, '');if(!p.startsWith('media/')||p.split('/').includes('..')||!fs.statSync(path.join(root,p),{throwIfNoEntry:false})?.isFile())throw Error('画像が見つかりません: '+value);return p;}
const profiles=[],images=[],ids=new Set();
for(let world=0;world<3;world++){
 const p=read(`content/worlds/${world}.json`);if(!p.name?.trim())throw Error('世界観の名前を入力してください。');
 const members=(p.members||[]).map((c,index)=>{if(!c.name?.trim())throw Error('キャラクター名を入力してください。');return {...c,id:c.id||`character-${world}-${index}`,thumbnail:media(c.thumbnail),art:[c.standing,...(c.settings||[])].filter(Boolean).map(media)}});
 profiles.push({...p,avatar:media(p.avatar),banner:media(p.banner),members});
 const folder=`content/gallery/${world}`;const posts=fs.readdirSync(folder).filter(f=>f.endsWith('.json')).map(f=>({file:f,...read(`${folder}/${f}`)})).filter(p=>p.published!==false).sort((a,b)=>(Number(a.order)||0)-(Number(b.order)||0)||a.file.localeCompare(b.file));
 for(const post of posts){if(!post.pages?.length)throw Error(`画像を1枚以上登録してください: ${post.file}`);const id=post.id||`${world}-${post.file}`;if(ids.has(id))throw Error('投稿IDが重複しています: '+id);ids.add(id);const pages=post.pages.map(media);images.push({...post,id,character:world,src:pages[0],pages,type:pages.length>1?'series':'single',tags:[...new Set((post.tags||[]).map(t=>String(t).trim().replace(/^#/, '')).filter(Boolean))]});}
}
// Validate first. Only replace the previous output once all content is valid.
fs.rmSync(out,{recursive:true,force:true});fs.mkdirSync(path.join(out,'data'),{recursive:true});
for(const entry of ['assets','media','index.html'])fs.cpSync(path.join(root,entry),path.join(out,entry),{recursive:true});
fs.writeFileSync(path.join(out,'data/gallery.json'),JSON.stringify({profiles,images},null,2)+'\n');fs.writeFileSync(path.join(out,'.nojekyll'),'');
console.log(`Built: ${profiles.length} worlds, ${profiles.reduce((n,p)=>n+p.members.length,0)} characters, ${images.length} posts`);
