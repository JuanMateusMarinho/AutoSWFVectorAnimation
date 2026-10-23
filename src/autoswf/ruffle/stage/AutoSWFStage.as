package {
    import flash.display.DisplayObject;
    import flash.display.GradientType;
    import flash.display.Loader;
    import flash.display.MovieClip;
    import flash.display.Sprite;
    import flash.events.Event;
    import flash.events.KeyboardEvent;
    import flash.events.MouseEvent;
    import flash.events.UncaughtErrorEvent;
    import flash.geom.ColorTransform;
    import flash.geom.Matrix;
    import flash.geom.Point;
    import flash.system.ApplicationDomain;
    import flash.system.LoaderContext;
    import flash.text.TextField;
    import flash.utils.ByteArray;
    import flash.utils.Dictionary;

    /** AutoSWF's test stage for Ruffle (spec §5). It stands in for AQW's Game root (stage.getChildAt(0)): it has the
     *  world's flags and mcSetColor, loads the embedded armor and puts it on an avatar stand-in (AutoSWFAvatar) next to
     *  a target dummy, with every animation in a list, an AQW-like skill bar, player colors, pause, frame steps, zoom
     *  and backgrounds. Clicking the ground walks the avatar there. */
    public class AutoSWFStage extends MovieClip {
        public static const W:int = 960;
        public static const H:int = 600;
        public static const AREA:int = 740;
        public static const RANGE:Number = 140;
        public static const HIT_DELAY:int = 8;
        public static const ZOOMS:Array = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4];
        /** The user's default first: a 55% gray (#8C8C8C). */
        public static const BACKGROUNDS:Array = ["Gray 55%", "Sky", "Light", "Dark", "Green"];

        public var world:Object = {bitWalk: true};
        public var settings:Object;
        public var colors:Object;
        public var gender:String;
        public var avatar:AutoSWFAvatar;
        public var face:MovieClip;
        public var dummy:AutoSWFDummy;
        public var actors:Sprite = new Sprite();
        public var backdrop:Sprite = new Sprite();
        public var status:TextField;
        public var controls:Sprite = new Sprite();
        public var bar:AutoSWFSkillBar;
        public var panel:Sprite = new Sprite();
        public var list:AutoSWFList;
        public var palette:AutoSWFPalette;
        public var genderButtons:Array = [];
        public var playback:AutoSWFPlayback;
        public var armorError:String;
        public var background:int = 0;
        public var zoom:int = 2;
        /** What is playing: {kind: "label" | "motion", name}. */
        public var current:Object = {kind: "label", name: "Idle"};
        private var colored:Dictionary = new Dictionary(true);
        private var loader:Loader;
        private var dummyLoader:Loader;
        private var domain:ApplicationDomain;
        private var pauseButton:AutoSWFButton;
        private var zoomText:TextField;
        private var nextAuto:String = "Attack1";
        private var hitIn:int = -1;
        private var motionRange:Array;

        public function AutoSWFStage() {
            super();
            var json:ByteArray = new AutoSWFStageSettings();
            settings = JSON.parse(json.readUTFBytes(json.length));
            colors = settings.colors;
            gender = settings.genders.length > 0 ? settings.genders[0] : "M";
            playback = new AutoSWFPlayback(this);
            layout();
            setStatus("Loading the armor…");
            loaderInfo.uncaughtErrorEvents.addEventListener(UncaughtErrorEvent.UNCAUGHT_ERROR, onUncaught);
            var armor:ByteArray = new AutoSWFArmorBytes();
            var context:LoaderContext = new LoaderContext(false, ApplicationDomain.currentDomain);
            context.allowCodeImport = true;
            loader = new Loader();
            loader.uncaughtErrorEvents.addEventListener(UncaughtErrorEvent.UNCAUGHT_ERROR, onUncaught);
            loader.contentLoaderInfo.addEventListener(Event.COMPLETE, onArmor);
            loader.loadBytes(armor, context);
        }

        // ------------------------------------------------------------ layout

        private function layout():void {
            backdrop.addEventListener(MouseEvent.CLICK, onGround);
            addChild(backdrop);
            drawBackground();
            actors.x = AREA / 2;
            actors.y = 470;
            addChild(actors);
            dummy = new AutoSWFDummy();
            dummy.x = 160;
            dummy.addEventListener(MouseEvent.CLICK, function (e:MouseEvent):void { dummy.selected = !dummy.selected; });
            actors.addChild(dummy);

            status = AutoSWFButton.text("", 12, 0xFFFFFF);
            status.background = true;
            status.backgroundColor = 0x000000;
            status.x = 8;
            status.y = 8;
            addChild(status);

            var x:Number = 0;
            pauseButton = control("Pause", 58, x, togglePause);
            x += 62;
            control("< Frame", 62, x, function ():void { playback.step(-1); });
            x += 66;
            control("Frame >", 62, x, function ():void { playback.step(1); });
            x += 72;
            control("Zoom -", 52, x, function ():void { zoomBy(-1); });
            x += 56;
            zoomText = AutoSWFButton.text("100%", 11, 0xFFFFFF);
            zoomText.background = true;
            zoomText.backgroundColor = 0x000000;
            zoomText.x = x;
            zoomText.y = 3;
            controls.addChild(zoomText);
            x += 40;
            control("+", 26, x, function ():void { zoomBy(1); });
            x += 36;
            control("Background", 82, x, cycleBackground);
            controls.x = AREA - 8 - (x + 82);
            controls.y = 6;
            addChild(controls);

            panel.x = AREA;
            panel.graphics.beginFill(0x19120A, 0.97);
            panel.graphics.drawRect(0, 0, W - AREA, H);
            panel.graphics.endFill();
            panel.graphics.lineStyle(2, AutoSWFButton.GOLD);
            panel.graphics.moveTo(1, 0);
            panel.graphics.lineTo(1, H);
            addChild(panel);
            stage_keys();
        }

        private function control(text:String, w:Number, x:Number, onClick:Function):AutoSWFButton {
            var b:AutoSWFButton = new AutoSWFButton(text, w, 22, onClick);
            b.x = x;
            controls.addChild(b);
            return b;
        }

        /** The list, the colors, the skill bar and the Male/Female switch (they need the settings and the gender). */
        private function fillPanel():void {
            var top:Number = 6;
            for each (var old:DisplayObject in genderButtons) panel.removeChild(old);
            genderButtons = [];
            if (settings.genders.length > 1) {
                for (var i:int = 0; i < settings.genders.length; i++) {
                    var g:String = settings.genders[i];
                    var b:AutoSWFButton = new AutoSWFButton(g == "F" ? "Female" : "Male", 100, 22, genderOf(g));
                    b.x = 8 + i * 106;
                    b.y = top;
                    b.selected = g == gender;
                    panel.addChild(b);
                    genderButtons.push(b);
                }
                top += 30;
            }
            if (list == null) {
                palette = new AutoSWFPalette(this);
                palette.y = H - 104;
                panel.addChild(palette);
            }
            if (list != null) panel.removeChild(list);
            list = new AutoSWFList(this, W - AREA - 4, palette.y - top - 8);
            list.x = 2;
            list.y = top;
            panel.addChild(list);
            list.fill(gender);
            if (bar != null) removeChild(bar);
            bar = new AutoSWFSkillBar(this, settings.skills[gender] || []);
            bar.x = Math.round((AREA - bar.width) / 2);
            bar.y = H - bar.height - 6;
            addChild(bar);
        }

        private function genderOf(g:String):Function {
            return function ():void { setGender(g); };
        }

        private function drawBackground():void {
            var gr:* = backdrop.graphics;
            gr.clear();
            var name:String = BACKGROUNDS[background];
            if (name == "Sky") {
                var m:Matrix = new Matrix();
                m.createGradientBox(AREA, 400, Math.PI / 2, 0, 0);
                gr.beginGradientFill(GradientType.LINEAR, [0x6F8FB0, 0xA9BFD0], [1, 1], [0, 255], m);
                gr.drawRect(0, 0, AREA, 400);
                gr.endFill();
                gr.beginFill(0x66764F);
                gr.drawRect(0, 400, AREA, H - 400);
                gr.endFill();
            } else {
                gr.beginFill(name == "Gray 55%" ? 0x8C8C8C : name == "Light" ? 0xD9D9D9 : name == "Dark" ? 0x333333
                    : 0x00B140);
                gr.drawRect(0, 0, AREA, H);
                gr.endFill();
            }
        }

        // ------------------------------------------------------------ the armor

        private function onArmor(e:Event):void {
            domain = loader.contentLoaderInfo.applicationDomain;
            showAvatar();
            addEventListener(Event.ENTER_FRAME, onFrame);
            var bytes:ByteArray = new AutoSWFDummyBytes();
            if (settings.dummy != null && bytes.length > 0) {
                var context:LoaderContext = new LoaderContext(false, new ApplicationDomain(ApplicationDomain.currentDomain));
                context.allowCodeImport = true;
                dummyLoader = new Loader();
                dummyLoader.uncaughtErrorEvents.addEventListener(UncaughtErrorEvent.UNCAUGHT_ERROR, onUncaught);
                dummyLoader.contentLoaderInfo.addEventListener(Event.COMPLETE, onDummy);
                dummyLoader.loadBytes(bytes, context);
            } else {
                startSelfTest();
            }
        }

        /** AQW's Training Dummy, from the user's cache: it replaces the drawn stand-in. */
        private function onDummy(e:Event):void {
            var Monster:Class = dummyLoader.contentLoaderInfo.applicationDomain.getDefinition(settings.dummy) as Class;
            dummy.wear(new Monster() as MovieClip);
            startSelfTest();
        }

        private function startSelfTest():void {
            if (loaderInfo.parameters.selftest == "1") new AutoSWFSelfTest(this).start();
        }

        /** A fresh avatar wearing the armor of the current gender, playing Idle. */
        public function showAvatar():void {
            var at:Point = avatar != null ? new Point(avatar.x, avatar.y) : new Point(-90, 0);
            if (avatar != null) actors.removeChild(avatar);
            playback.paused = false;
            avatar = new AutoSWFAvatar(settings.slots, settings.head[gender] || {});
            avatar.onError = armorStopped;
            avatar.x = at.x;
            avatar.y = at.y;
            actors.addChildAt(avatar, 0);
            fillPanel();
            try {
                face = avatar.mcChar.wear(domain, settings.link, gender);
            } catch (err:Error) {
                armorStopped(err.message);
            }
            playGameLabel("Idle");
        }

        public function setGender(g:String):void {
            if (g == gender) return;
            gender = g;
            showAvatar();
        }

        public function armorStopped(message:String):void {
            armorError = message;
            log("armor error: " + message);
        }

        private function onUncaught(e:UncaughtErrorEvent):void {
            e.preventDefault();
            armorStopped(e.error is Error ? Error(e.error).message : String(e.error));
        }

        // ------------------------------------------------------------ playing

        /** A game label as AQW plays it (Skills go through useSkill so they aim at the selected dummy). */
        public function playGameLabel(name:String):void {
            if (rowOf(name) != null && rowOf(name).group == "Skills" && name != "Idle") {
                useSkill(name);
                return;
            }
            started("label", name);
            avatar.playLabel(name);
        }

        /** One of the armor's own animations by name: one-frame labels hold (their body clip restarts), longer ones
         *  loop over their frames. */
        public function playMotion(name:String):void {
            started("motion", name);
            if (face == null) return;
            var labels:Array = face.currentLabels.sortOn("frame", Array.NUMERIC);
            motionRange = null;
            for (var i:int = 0; i < labels.length; i++) {
                if (labels[i].name != name) continue;
                var end:int = i + 1 < labels.length ? labels[i + 1].frame : face.totalFrames + 1;
                motionRange = [labels[i].frame, end];
            }
            if (motionRange == null) return;
            if (motionRange[1] - motionRange[0] == 1) {
                face.gotoAndStop(name);
                var body:MovieClip = face.getChildByName("body") as MovieClip;
                if (body != null) body.gotoAndPlay(1);
                motionRange = null;
            } else {
                face.gotoAndPlay(name);
            }
        }

        /** A skill: with the dummy selected, walk into range first and face it; the dummy is hit a few frames later. */
        public function useSkill(game:String):void {
            if (dummy.selected && Math.abs(dummy.x - avatar.x) > RANGE) {
                var side:Number = dummy.x > avatar.x ? -1 : 1;
                avatar.walkTo(dummy.x + side * RANGE * 0.8, dummy.y, function ():void { fire(game); });
                current = {kind: "label", name: "Walk"};
                return;
            }
            fire(game);
        }

        private function fire(game:String):void {
            if (dummy.selected) avatar.face(dummy.x - avatar.x);
            started("label", game);
            avatar.playLabel(game);
            hitIn = dummy.selected ? HIT_DELAY : -1;
        }

        public function autoAttack():void {
            var game:String = nextAuto;
            nextAuto = nextAuto == "Attack1" ? "Attack2" : "Attack1";
            useSkill(game);
        }

        /** Play again what is playing, from its start (frame steps back use it). */
        public function replay():void {
            if (current.kind == "motion") playMotion(current.name);
            else {
                started("label", current.name);
                avatar.playLabel(current.name);
            }
        }

        private function started(kind:String, name:String):void {
            if (playback.paused) resume();
            if (kind == "label") motionRange = null;
            current = {kind: kind, name: name};
            playback.restarted();
            if (list != null) list.highlight(kind, name);
        }

        public function rowOf(name:String):Object {
            for each (var r:Object in settings.labels) {
                if (r.name == name) return r;
            }
            return null;
        }

        private function onGround(e:MouseEvent):void {
            if (playback.paused) return;
            var p:Point = actors.globalToLocal(new Point(e.stageX, e.stageY));
            if (p.y < -90 || p.y > 110) return;
            avatar.walkTo(p.x, p.y);
            current = {kind: "label", name: "Walk"};
            if (list != null) list.highlight("label", "Walk");
        }

        private function onFrame(e:Event):void {
            playback.tick();
            if (!playback.paused && motionRange != null && face != null &&
                    (face.currentFrame < motionRange[0] || face.currentFrame >= motionRange[1])) {
                face.gotoAndPlay(motionRange[0]);
            }
            if (!playback.paused && hitIn >= 0 && hitIn-- == 0) dummy.hit();
            updateStatus();
        }

        // ------------------------------------------------------------ controls

        public function togglePause():void {
            if (playback.paused) resume();
            else {
                playback.pause();
                pauseButton.setText("Play");
            }
        }

        private function resume():void {
            playback.resume();
            pauseButton.setText("Pause");
        }

        public function zoomBy(step:int):void {
            zoom = Math.max(0, Math.min(ZOOMS.length - 1, zoom + step));
            actors.scaleX = actors.scaleY = ZOOMS[zoom];
            zoomText.text = Math.round(ZOOMS[zoom] * 100) + "%";
        }

        public function cycleBackground():void {
            background = (background + 1) % BACKGROUNDS.length;
            drawBackground();
        }

        private function stage_keys():void {
            addEventListener(Event.ADDED_TO_STAGE, function (e:Event):void {
                stage.addEventListener(KeyboardEvent.KEY_DOWN, onKey);
            });
            if (stage != null) stage.addEventListener(KeyboardEvent.KEY_DOWN, onKey);
        }

        private function onKey(e:KeyboardEvent):void {
            var slots:Array = settings.skills[gender] as Array;
            if (e.keyCode >= 49 && e.keyCode <= 53 && slots != null && slots.length > e.keyCode - 49) {
                useSkill(slots[e.keyCode - 49].game);
            } else if (e.keyCode == 65) autoAttack();
            else if (e.keyCode == 32) togglePause();
            else if (e.keyCode == 37) playback.step(-1);
            else if (e.keyCode == 39) playback.step(1);
            else if (e.keyCode == 187 || e.keyCode == 107) zoomBy(1);
            else if (e.keyCode == 189 || e.keyCode == 109) zoomBy(-1);
            else if (e.keyCode == 66) cycleBackground();
        }

        /** "<game label> → <armor animation> · frame n / total · paused" (frames of the head's body clip when it has
         *  one, as release-style armors play their animation there; else of the head's own label). */
        private function updateStatus():void {
            if (face == null) return;
            var row:Object = current.kind == "label" ? rowOf(current.name) : null;
            var text:String = current.kind == "motion" ? "Armor: " + current.name : current.name;
            if (row != null && row.armor[gender] != null && row.armor[gender] != current.name) {
                text += "  →  " + row.armor[gender];
            }
            var body:MovieClip = face.getChildByName("body") as MovieClip;
            var clip:MovieClip = body != null ? body : face;
            text += "  ·  frame " + clip.currentFrame + " / " + clip.totalFrames;
            if (playback.paused) text += "  ·  paused";
            if (avatar.walking) text += "  ·  walking";
            if (armorError != null) text += "\nThe armor's code stopped: " + armorError;
            status.text = text;
        }

        // ------------------------------------------------------------ AQW's Game.mcSetColor

        /** The clip becomes one flat tint of the player's color, shaded (Light +100, Dark -50 with Skin red -25,
         *  Darker -125); remembered so a color change re-tints it. */
        public function mcSetColor(clip:MovieClip, location:String, shade:String):void {
            colored[clip] = [location, shade];
            tint(clip, location, shade);
        }

        public function setPlayerColor(location:String, rgb:uint):void {
            colors[location] = rgb;
            for (var key:Object in colored) {
                if (colored[key][0] == location) tint(MovieClip(key), location, colored[key][1]);
            }
            if (palette != null) palette.refresh();
        }

        private function tint(clip:MovieClip, location:String, shade:String):void {
            var rgb:uint = uint(colors[location]);
            var s:String = String(shade).toUpperCase();
            var offset:int = s == "LIGHT" ? 100 : s == "DARK" ? -50 : s == "DARKER" ? -125 : 0;
            var red:int = s == "DARK" && location == "Skin" ? -25 : offset;
            clip.transform.colorTransform = new ColorTransform(0, 0, 0, 1, ((rgb >> 16) & 255) + red,
                ((rgb >> 8) & 255) + offset, (rgb & 255) + offset, 0);
        }

        public function setStatus(text:String):void {
            status.text = text;
        }

        public function log(text:String):void {
            trace("AUTOSWF " + text);
        }
    }
}
